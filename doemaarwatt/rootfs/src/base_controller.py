from abc import ABC, abstractmethod
import asyncio
import time
from datetime import datetime as dt
from typing import Optional
from zoneinfo import ZoneInfo
import os

from aiohttp import web
import aiohttp

from config import DoeMaarWattConfig, ControlMode
from common import Logger, Phase, ProgrammingError, PBSapp, SINGLE_PHASES, BaseInverter
from stats import ControllerStats
from safety import (BatterySoCLimitsMixin, BatteryChargeLimitsMixin,
                    MainFuseProtectionMixin)
from subsystems.battery_inverters import BaseBatteryInverter, create_battery_inverter, BatteryInverterStats
from subsystems.solar_inverters import BaseSolarInverter, create_solar_inverter, SolarInverterStats
from subsystems.energy_meters import BaseEnergyMeter, create_energy_meter, EnergyMeterStats
from subsystems.ev_chargers import BaseEVCharger, create_ev_charger, EVChargerStats


RECONNECT_DELAY = 10 # seconds before attempting a reconnect
LOOP_DELAY = 10 # control loop delay

# Phase current difference handling (issue #18): too large a current difference between two phases at the
# grid connection trips the main circuit breaker. This typically happens when one inverter falls back to its
# own charge/discharge behaviour while the others are still controlled in the opposite direction.
PHASE_DIFF_TOLERANCE_A = 0.1     # difference overshoot below which no correction is made
PHASE_DIFF_MAX_ITERATIONS = 6    # safety bound on the correction loop
NOMINAL_PHASE_VOLTAGE = 230.0    # fallback when the energy meter reports no voltage for a phase

# Solar curtailment (issues #29, #31): a solar inverter generating within this margin of the output cap in force
# is taken to be held back by that cap, so its measured generation says nothing about what the sun delivers.
SOLAR_AT_CAP_MARGIN_PCT = 3.0    # margin as a percentage of the cap ...
SOLAR_AT_CAP_MARGIN_W = 100.0    # ... but at least this many Watts (per phase)
# Room (per phase) a solar inverter is given above its present generation whenever its cap binds, so it is
# not mistaken for being held back when it is not: must stay well clear of the at-cap margin above.
SOLAR_ROOM_PCT = 6.0             # room as a percentage of the present generation ...
SOLAR_ROOM_W = 250.0             # ... but at least this many Watts


class BaseController(
    ABC,
    BatterySoCLimitsMixin,
    BatteryChargeLimitsMixin,
    MainFuseProtectionMixin,
):
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        self.config = cfg
        self.log = log

        self.running = False
        self.stats = ControllerStats()
        self.inv_control = {} # stats per inverter

        # set up by setup()
        self.battery_inverters: list[BaseBatteryInverter] = []
        self.solar_inverters: list[BaseSolarInverter] = []
        self.ev_chargers: list[BaseEVCharger] = []
        self.inverters: dict[str, BaseInverter] = {} # inverter name -> BaseInverter
        self.energy_meter: Optional[BaseEnergyMeter] = None

        # mapping of each phase to all connected and enabled inverters (battery and solar) to it
        self.inv_phase_map: dict[Phase, list[str]] = None  # type: ignore

        self.tz: ZoneInfo = None  # type: ignore

    @property
    def mode(self) -> ControlMode:
        raise NotImplementedError

    def stop(self) -> None:
        self.running = False
        self.stats.reset()

    async def reconnect_delay(self):
        if self.running:
            await asyncio.sleep(RECONNECT_DELAY)

    async def loop_delay(self):
        await asyncio.sleep(self.config.get_general_config().get('loop_delay', LOOP_DELAY))

    def setup(self) -> None:
        bat_inv_cfg = self.config.get_battery_inverters_config()
        sol_inv_cfg = self.config.get_solar_inverters_config()
        ev_cfg = self.config.get_ev_chargers_config()
        em_cfg = self.config.get_energy_meter_config()

        self.battery_inverters = [
            create_battery_inverter(cfg, self.log)
            for cfg in bat_inv_cfg
            if len(cfg) > 0 and cfg.get('enable', True)
        ]
        self.solar_inverters = [
            create_solar_inverter(cfg, self.log)
            for cfg in sol_inv_cfg
            if len(cfg) > 0 and cfg.get('enable', True)
        ]
        self.ev_chargers = [
            create_ev_charger(cfg, self.log)
            for cfg in ev_cfg
            if len(cfg) > 0 and cfg.get('enable', True)
        ]

        for inv in self.battery_inverters + self.solar_inverters + self.ev_chargers:
            if inv.name in self.inverters:
                raise ProgrammingError(f'inverters should have a unique name: {inv.name}', source='base_controller')
            self.inverters[inv.name] = inv

        self.inv_phase_map = {
            phase: [
                i.name for i in self.battery_inverters + self.solar_inverters + self.ev_chargers
                if i.connected_phase == phase or i.connected_phase == Phase.ALL
            ]
            for phase in SINGLE_PHASES
        }

        self.energy_meter = create_energy_meter(em_cfg, self.log) if len(em_cfg) > 0 else None

        self.tz = ZoneInfo(self.config.timezone)

    def handle_subsystem_error(self, subsystem, action: str, error: BaseException) -> None:
        '''Decide what becomes of an error a subsystem raised.

        Unless that subsystem is configured with ignore_errors, the error is re-raised and reaches the control
        loop, which relinquishes control of everything and reconnects - which is the right answer when the
        installation as a whole can no longer be trusted. With ignore_errors it is logged and the caller
        carries on without this one subsystem: it is left out of this pass and, its stats having gone unread,
        is reported as UNCONTROLLED, so the safety checks treat it as something they cannot command rather
        than something that is behaving.

        A cancellation is never ignored: that is the add-on shutting down, not a subsystem misbehaving.
        '''
        if isinstance(error, asyncio.CancelledError) or not getattr(subsystem, 'ignore_errors', False):
            raise error

        self.log.error(f'{subsystem.name}: error while {action} is ignored, as ignore_errors is set for this '
                       f'subsystem - it is left uncontrolled: {type(error).__name__}: {error}')

    async def gather_subsystems(self, subsystems: list, action: str, coros: list,
        best_effort: bool = False,
    ) -> list:
        '''Await one operation per subsystem and apply handle_subsystem_error to each failure. Returns a
        result per subsystem, None where it failed and the failure was ignored.

        best_effort logs every failure and never re-raises, whatever ignore_errors says. It is for tearing
        down - relinquishing control, closing connections - where there is nothing left to protect by
        stopping, and where giving up halfway would leave the remaining subsystems untouched. Losing the
        connection is exactly when relinquishing fails, and it is exactly then that the rest of the
        installation still has to be released and closed.
        '''
        results = await asyncio.gather(*coros, return_exceptions=True)

        ret = []
        for subsystem, result in zip(subsystems, results):
            if isinstance(result, BaseException):
                if best_effort and not isinstance(result, asyncio.CancelledError):
                    self.log.error(f'{subsystem.name}: error while {action}: {type(result).__name__}: {result}')
                else:
                    self.handle_subsystem_error(subsystem, action, result)
                ret.append(None)
            else:
                ret.append(result)

        return ret

    async def connect_subsystems(self):
        subsystems = list(self.inverters.values())
        await self.gather_subsystems(subsystems, 'connecting', [inv.connect() for inv in subsystems])

        if self.energy_meter:
            await self.gather_subsystems([self.energy_meter], 'connecting', [self.energy_meter.connect()])

        self.log.info(f'(re)connected to all subsystems')

    async def enable_control_subsystems(self):
        '''Put every subsystem in a state where it can be controlled. One that fails and has ignore_errors
        set is skipped, so a single stubborn inverter does not keep the rest from being controlled.
        '''
        subsystems = list(self.inverters.values())
        await self.gather_subsystems(subsystems, 'enabling control', [inv.enable_control() for inv in subsystems])

    def close_subsystems(self):
        subsystems: list[BaseInverter|BaseEnergyMeter] = list(self.inverters.values())
        if self.energy_meter:
            subsystems.append(self.energy_meter)

        # best effort, like relinquishing control: one subsystem that cannot be closed must not keep the
        # others from being closed, whatever its ignore_errors says
        for subsystem in subsystems:
            try:
                subsystem.close()
            except Exception as e:
                self.log.error(f'{subsystem.name}: error while disconnecting: {type(e).__name__}: {e}')

        self.log.info('disconnected from all subsystems')

    async def run(self) -> None:
        '''Run this controller. This entails calling its setup() method and then awaiting its loop() method
        '''
        self.running = True
        self.stats.start_ts = time.time()

        self.setup()

        await self.loop()  # must be implemented by the concrete subclass

    @abstractmethod
    def get_PBSapp(self, now: dt) -> PBSapp:
        '''
        Get the desired power level for each controlled inverter, ensuring each inverter's power limits
        '''
        raise NotImplementedError

    def get_export_limit(self, now: dt) -> Optional[float]:
        '''Per-phase ceiling (W) on power the controlled inverters may export to the grid, or None to use
        the main-fuse limit. Modes may override this to tighten the limit (e.g. to 0 during negative prices,
        so surplus generation is curtailed rather than exported). Applied by calc_PBSsent.'''
        return None

    @abstractmethod
    async def loop(self) -> None:
        raise NotImplementedError

    async def get_stats(self):
        '''Read the stats of every subsystem. One that fails and has ignore_errors set is recorded with
        default stats rather than with what it last reported: those say UNCONTROLLED and hold no measurements,
        which is what it is - and keeps the safety checks from acting on readings that are no longer true.
        '''
        if self.battery_inverters:
            bat_inv_stats = await self.gather_subsystems(self.battery_inverters, 'reading stats',
                                                         [inv.read_stats() for inv in self.battery_inverters])
            self.stats.battery_inverters = { inv.name: inv_stats if inv_stats is not None else BatteryInverterStats()
                                             for inv, inv_stats in zip(self.battery_inverters, bat_inv_stats) }

        if self.solar_inverters:
            sol_inv_stats = await self.gather_subsystems(self.solar_inverters, 'reading stats',
                                                         [inv.read_stats() for inv in self.solar_inverters])
            self.stats.solar_inverters = { inv.name: inv_stats if inv_stats is not None else SolarInverterStats()
                                           for inv, inv_stats in zip(self.solar_inverters, sol_inv_stats) }

        if self.ev_chargers:
            ev_stats = await self.gather_subsystems(self.ev_chargers, 'reading stats',
                                                    [inv.read_stats() for inv in self.ev_chargers])
            self.stats.ev_chargers = { inv.name: inv_stats if inv_stats is not None else EVChargerStats()
                                       for inv, inv_stats in zip(self.ev_chargers, ev_stats) }

        if self.energy_meter is not None:
            # NOTE: ignoring an error here clears the grid measurements rather than keeping stale ones, and
            # the safety checks cannot command anything without them: see BaseEnergyMeter.ignore_errors
            em_stats = await self.gather_subsystems([self.energy_meter], 'reading stats',
                                                    [self.energy_meter.read_stats()])
            self.stats.energy_meter = em_stats[0]

    # def _phase_voltage(self, phi: Phase) -> float:
    #     '''Measured grid voltage of a phase, used to convert between power (W) and current (A). Falls back to
    #     the nominal phase voltage when the energy meter does not report one.
    #     '''
    #     em = self.stats.energy_meter
    #     voltage = em.grid[phi].voltage if em is not None and phi in em.grid else None
    #     return voltage if voltage else NOMINAL_PHASE_VOLTAGE

    # def _inverter_stats(self, inv_name: str) -> Optional[BatteryInverterStats | SolarInverterStats | EVChargerStats]:
    #     '''Latest stats of a battery or solar inverter, or None when it has not been read (yet).'''
    #     if inv_name in self.stats.battery_inverters:
    #         return self.stats.battery_inverters[inv_name] # can be None
    #     if inv_name in self.stats.solar_inverters:
    #         return self.stats.solar_inverters[inv_name] # can be None
    #     if inv_name in self.stats.ev_chargers:
    #         return self.stats.ev_chargers[inv_name] # can be None

    #     raise ProgrammingError(f'inverter {inv_name} is neither a battery, solar inverter nor an EV charger',
    #                            source='base_controller.py', requires_fallback=True)

    # def _follows_command(self, inv_name: str) -> bool:
    #     '''True when an inverter is fully under our control, and can therefore be expected to settle on the
    #     power level we command it. An inverter that is uncontrolled or only partially controlled runs its own
    #     charge/discharge behaviour: its power can neither be predicted from PBSsent nor be turned down.
    #     '''
    #     stats = self._inverter_stats(inv_name)
    #     return stats is not None and stats.control_status == ControlStatus.NOMINAL

    # def _measured_phase_power(self, phi: Phase, inv_name: str) -> Optional[float]:
    #     '''Last measured power (PBSnow) of an inverter on a phase, or None when it could not be read.'''
    #     stats = self._inverter_stats(inv_name)
    #     spc = stats.ac_side.get(phi) if stats is not None else None
    #     return None if spc is None else spc.power

    # def _solar_at_cap(self, inv_name: str, measured: Optional[float]) -> bool:
    #     '''True when a solar inverter is generating at (or within a small margin of) the output cap that is in
    #     force, i.e. the one it reports, which is the cap commanded in a previous cycle. Its generation is then
    #     held back by that cap: the sun may well deliver more, which the measurement does not show.
    #     '''
    #     inv = self.inverters[inv_name]
    #     stats = self.stats.solar_inverters.get(inv_name) if isinstance(inv, BaseSolarInverter) else None
    #     if measured is None or stats is None or stats.setpoint_limit_w is None:
    #         return False

    #     # the setpoint caps the total across all connected phases, the measurement is for a single phase
    #     cap_phase = stats.setpoint_limit_w / (3 if inv.connected_phase == Phase.ALL else 1)
    #     margin = max(SOLAR_AT_CAP_MARGIN_W, cap_phase * SOLAR_AT_CAP_MARGIN_PCT / 100)
    #     return measured >= cap_phase - margin

    # def _effective_power(self, inv_name: str, commanded: float, measured: Optional[float]) -> float:
    #     '''Power (W) an inverter is expected to settle on for a commanded power level (issue #29). A battery
    #     inverter settles on what it is commanded. For a solar inverter the command is only a ceiling on its
    #     output: it cannot generate more than the sun delivers, so it is expected to stay at its measured
    #     generation while that is below the ceiling. The ceiling is assumed instead (worst case) when there is
    #     no measurement, and when the inverter runs at the cap it currently has (see _solar_at_cap): lifting or
    #     raising that cap may let it generate anything up to the new ceiling. Taking the measurement there would
    #     have the cap lifted the very next cycle, just because the capped generation fits (issue #31).
    #     '''
    #     if measured is None or not isinstance(self.inverters[inv_name], BaseSolarInverter):
    #         return commanded
    #     if self._solar_at_cap(inv_name, measured):
    #         return commanded
    #     return min(commanded, max(0.0, measured))

    # def _projected_grid_power(self, phi: Phase, intended_PBSsent_for_phase: PhasePowerMap, bound: int) -> float:
    #     '''Power (W) the grid connection of a phase is projected to carry once the commanded PBSsent values
    #     have taken effect (issue #18). Negative means importing from the grid, positive exporting.

    #     The projection is anchored on what the energy meter reads right now, which already accounts for both
    #     the inverters and everything else on the phase (a heat pump, an EV charger, ...). Only the change each
    #     inverter is expected to make to its present output is added on top. Working in changes rather than
    #     absolute power means the non-inverter load never has to be estimated separately, and nothing is
    #     counted twice - the present output of every inverter is already in the meter reading:
    #         - an inverter we control moves from its measured power to what we command (for a solar inverter
    #           the command is only a ceiling, see _effective_power)
    #         - an inverter that runs its own charge/discharge behaviour is assumed to stay where it is: it
    #           ignores what we command, but the meter already accounts for what it is doing
    #         - an inverter that cannot be read at all may swing anywhere within its power limits without us
    #           noticing, which makes the phase a range rather than a single power level. bound +1 grants every
    #           such inverter its largest possible increase (charge limit -> discharge limit) and so returns the
    #           upper bound of the phase, -1 the largest decrease and so the lower bound.
    #     '''
    #     em = self.stats.energy_meter
    #     PGnow = em.grid[phi].power if em is not None and phi in em.grid else None
    #     if PGnow is None:
    #         raise ProgrammingError(f'missing grid power measurement for {phi}', source='base_controller.py')

    #     total = PGnow
    #     for inv_name, intended_PBSsent in intended_PBSsent_for_phase.inv_power.items():
    #         measured = self._measured_phase_power(phi, inv_name)
    #         if measured is None:
    #             low, high = self.inverters[inv_name].power_limits_phase
    #             total += (high - low) if bound > 0 else (low - high)
    #         elif self._follows_command(inv_name):
    #             total += self._effective_power(inv_name, intended_PBSsent, measured) - measured

    #     return total

    # def _unknown_power_inverters(self, PBSsent_phases: dict[Phase, PhasePowerMap]) -> list[str]:
    #     '''Inverters whose power could not be read, and whose contribution to a phase is therefore unknown.'''
    #     return sorted({
    #         inv_name
    #         for phi in SINGLE_PHASES
    #         for inv_name in PBSsent_phases[phi].inv_power
    #         if self._measured_phase_power(phi, inv_name) is None
    #     })

    # def _reducible_inverters(self, phi: Phase, ppm: PhasePowerMap, sign: int) -> dict[str, float]:
    #     '''Commanded power of the inverters on a phase that can still be turned down towards zero to pull that
    #     phase back towards the other phases: sign +1 selects the discharging/generating ones, -1 the charging
    #     ones. Inverters that are not fully controlled are excluded (they ignore what we command), and so are
    #     inverters connected to all three phases: those load every phase equally, so turning them down does not
    #     change the difference between phases.
    #     '''
    #     effective = { i: self._effective_power(i, p, self._measured_phase_power(phi, i)) for i, p in ppm.inv_power.items() }
    #     return {
    #         inv_name: power
    #         for inv_name, power in effective.items()
    #         if sign * power > 0
    #         and self.inverters[inv_name].connected_phase != Phase.ALL
    #         and self._follows_command(inv_name)
    #     }

    # def _reduce_phase_power(self, phi: Phase, ppm: PhasePowerMap, sign: int, reduction_w: float) -> None:
    #     '''Turn down the commanded power of the reducible inverters on a phase by reduction_w in total. The
    #     battery inverters are turned down before any solar inverter is curtailed, the same order calc_PBSsent
    #     uses for the grid limits (issue #31): curtailed solar generation is lost for good, whereas holding a
    #     battery back only defers its charge/discharge.

    #     Power levels only ever move towards zero. Unlike calc_PBSsent, a battery is never taken past standby
    #     into charging (or into discharging) to absorb a difference: the caller has settled every phase within
    #     the limits of the main fuse, and only reducing keeps that result reachable. The caller is responsible
    #     for capping reduction_w so the phase does not cross those limits in the other direction.
    #     '''
    #     reducible = self._reducible_inverters(phi, ppm, sign)
    #     if not reducible:
    #         return  # nothing on this phase can be turned down

    #     solar_names = { inv.name for inv in self.solar_inverters }
    #     # battery inverters first (sort key False < True), then the solar inverters:
    #     ordered = sorted(reducible.items(), key=lambda kv: kv[0] in solar_names)

    #     remaining_w = reduction_w
    #     for inv_name, power in ordered:
    #         if remaining_w <= 0:
    #             break

    #         reduction = min(abs(power), remaining_w)  # never past zero
    #         limited = power - sign * reduction
    #         remaining_w -= reduction

    #         self.log.info(f'{phi}: limiting {inv_name} PBSsent from {power:.0f} W to {limited:.0f} W '
    #                       f'to keep the current difference between the phases within limits')
    #         ppm.inv_power[inv_name] = limited

    # def apply_phase_current_diff_limits(self, PBSsent_phases: dict[Phase, PhasePowerMap]) -> None:
    #     '''Keep the current difference between any two phases within the configured limit (issue #18).

    #     The main circuit breaker trips when the currents of two phases differ too much, which happens when one
    #     inverter falls back to its own charge/discharge behaviour while the others are still being controlled
    #     in the opposite direction (eg. one inverter discharging at +25 A on L1 while another is commanded to
    #     charge at -25 A on L2).

    #     The check is made on the current each phase is projected to draw from (or supply to) the grid
    #     connection once PBSsent has taken effect (see _projected_grid_power), which is what the main fuse
    #     actually carries: the inverters plus everything else on the phase. An inverter whose power cannot be
    #     read may swing either way, which makes each phase a range rather than a single current, so the pair
    #     that is checked is the phase with the highest upper bound against the phase with the lowest lower
    #     bound. That covers all three combinations (L1-L2, L2-L3, L1-L3) in both directions: if the widest pair
    #     is within the limit, every other pair is too.

    #     Whenever that pair is over the limit, the band all phases lie in is narrowed to the limit: every phase
    #     above a ceiling is turned down to it, and every phase below a floor is pulled up to it, with the ceiling
    #     and floor exactly the limit apart. Narrowing the band rather than only the widest pair matters when two
    #     phases tie for an extreme: turning down just one of them leaves the difference as it was, so either all
    #     of them are corrected together or none of them is turned down for nothing. Where possible half of the
    #     overshoot is taken at the top and half at the bottom, and whatever one side cannot give at the other.

    #     Correcting a phase means turning its controlled inverters down towards zero - battery inverters first,
    #     solar inverters only for what the batteries cannot take (issue #31). A correction is additionally capped
    #     so it cannot push a phase past the main-fuse limits that calc_PBSsent just settled: turning down a
    #     battery that was covering a load makes its phase import more, and turning down a charging battery makes
    #     its phase export more. If the controlled inverters cannot bridge the difference on their own, they are
    #     turned down as far as that narrows the difference and the rest is logged as an error - a difference
    #     caused by the house load alone (eg. a single-phase EV charger) cannot be corrected by reducing inverters.
    #     '''
    #     limit_a = self.energy_meter.max_phase_current_diff_a if self.energy_meter is not None else 0
    #     if limit_a <= 0:  # not configured: no limit to enforce
    #         return

    #     voltages = { phi: self._phase_voltage(phi) for phi in SINGLE_PHASES }

    #     unknown = self._unknown_power_inverters(PBSsent_phases)
    #     if unknown:
    #         self.log.error(f'power level of {", ".join(unknown)} could not be read: assuming their worst case '
    #                        f'while limiting the current difference between the phases')

    #     for _ in range(PHASE_DIFF_MAX_ITERATIONS):
    #         upper = { phi: self._projected_grid_power(phi, PBSsent_phases[phi], +1) / voltages[phi] for phi in SINGLE_PHASES }
    #         lower = { phi: self._projected_grid_power(phi, PBSsent_phases[phi], -1) / voltages[phi] for phi in SINGLE_PHASES }

    #         # widest pair: the phase that can supply the most to the grid against the one that can draw the
    #         # most from it. Both ends are taken from a different phase, also when one phase holds both extremes
    #         hi, lo = max(((a, b) for a in SINGLE_PHASES for b in SINGLE_PHASES if a != b),
    #                      key=lambda pair: upper[pair[0]] - lower[pair[1]])
    #         excess_a = upper[hi] - lower[lo] - limit_a
    #         if excess_a <= PHASE_DIFF_TOLERANCE_A:
    #             return  # widest pair of phases is within the limit, so every other pair is safe as well

    #         # how far each phase can be turned down (down_a) or pulled up (up_a) by its controlled inverters,
    #         # capped by the room it still has before it hits the main fuse (checked against the pessimistic bound)
    #         down_a = { phi: min(
    #             sum(abs(p) for p in self._reducible_inverters(phi, PBSsent_phases[phi], +1).values()) / voltages[phi],
    #             max(0.0, lower[phi] - self._inv_control[phi]['PGmin'] / voltages[phi]),
    #         ) for phi in SINGLE_PHASES }
    #         up_a = { phi: min(
    #             sum(abs(p) for p in self._reducible_inverters(phi, PBSsent_phases[phi], -1).values()) / voltages[phi],
    #             max(0.0, self._inv_control[phi]['PGmax_export'] / voltages[phi] - upper[phi]),
    #         ) for phi in SINGLE_PHASES }

    #         # how far the top of the band (upper[hi]) can be lowered: every other phase that would end up above
    #         # the new top has to come down along with it, so the phase with the least room sets the pace. The
    #         # bottom end (lo) is left out: it never has to be below the top, only below the top of other phases.
    #         # Likewise for how far the bottom of the band (lower[lo]) can be raised
    #         max_down_a = max(0.0, min(down_a[phi] + upper[hi] - upper[phi] for phi in SINGLE_PHASES if phi != lo))
    #         max_up_a = max(0.0, min(up_a[phi] + lower[phi] - lower[lo] for phi in SINGLE_PHASES if phi != hi))

    #         # take half of the correction at each end, and whatever the one end cannot give from the other
    #         take_down_a = min(max_down_a, excess_a / 2)
    #         take_up_a = min(max_up_a, excess_a - take_down_a)
    #         take_down_a = min(max_down_a, excess_a - take_up_a)
    #         if take_down_a + take_up_a <= PHASE_DIFF_TOLERANCE_A:
    #             self.log.error(f'grid current difference between {hi} (at most {upper[hi]:+.1f} A) and {lo} '
    #                            f'(at least {lower[lo]:+.1f} A) exceeds the {limit_a} A limit by {excess_a:.1f} A, '
    #                            f'but the controlled inverters cannot narrow it any further')
    #             return

    #         self.log.info(f'grid current difference between {hi} (at most {upper[hi]:+.1f} A) and {lo} (at least '
    #                       f'{lower[lo]:+.1f} A) exceeds the {limit_a} A limit by {excess_a:.1f} A: turning down '
    #                       f'controlled inverters')

    #         ceiling_a = upper[hi] - take_down_a
    #         floor_a = lower[lo] + take_up_a
    #         for phi in SINGLE_PHASES:
    #             if phi != lo and upper[phi] - ceiling_a > PHASE_DIFF_TOLERANCE_A / 2:
    #                 self._reduce_phase_power(phi, PBSsent_phases[phi], +1, (upper[phi] - ceiling_a) * voltages[phi])
    #             if phi != hi and floor_a - lower[phi] > PHASE_DIFF_TOLERANCE_A / 2:
    #                 self._reduce_phase_power(phi, PBSsent_phases[phi], -1, (floor_a - lower[phi]) * voltages[phi])

    #     self.log.error(f'unable to bring the current difference between the phases within the {limit_a} A '
    #                    f'limit in {PHASE_DIFF_MAX_ITERATIONS} steps')

    async def command_PBSsent(self, now: dt) -> None:
        self.inv_control = {} # reset statistics for inverter control:
        self.log.info(f'computing safe charge/discharge amount (PBsent) for each phase:')
        assert isinstance(self.stats.energy_meter, EnergyMeterStats)

        # get the PBSapp per phase for each controlled inverter (battery and solar). EV chargers left out for now
        PBSapp_phases = self.get_PBSapp(now)

        # Now modify PBSapp in order to apply economic and safety checks to it and arrive at a PBSsent that
        # can be safely commanded to all inverters. Checks are applied in order of criticality with the
        # most critical checks being applied last:
        for safety_check_name in self.config.applicable_safety_checks:
            if not hasattr(self, safety_check_name):
                raise ProgrammingError(f'controller is missing safety check functionality for {safety_check_name}',
                                       source='BaseController')
            check_func = getattr(self, safety_check_name)
            if not callable(check_func):
                raise ProgrammingError(f'safety check method for {safety_check_name} is not callable',
                                       source='BaseController')

            # apply the safety check:
            check_func(PBSapp_phases, now=now)

        await self._command_PBSsent_battery_inverters(PBSapp_phases)
        await self._command_PBSsent_solar_inverters(PBSapp_phases)

    async def _command_PBSsent_battery_inverters(self, PBSapp_phases: PBSapp):
        # PBSapp is now safe: command each battery inverter exactly once. PBSsent values are per-phase, but set_power
        # expects the total across all connected phases, so scale by the number of phases the inverter spans
        # (1 for single-phase battery inverters, 3 for an inverter connected to ALL phases).
        self.log.info(f'sending charge/discharge amount (PBSsent) to enabled battery inverters:')
        commanded: set[str] = set()
        for phi in SINGLE_PHASES:
            # For the battery inverters for which we can command a power level directly:
            ppm = PBSapp_phases[phi]
            for inv_name, PBSsent in ppm.inv_power.items():
                if inv_name in commanded:
                    continue
                commanded.add(inv_name)

                inv = self.inverters[inv_name]
                if not isinstance(inv, BaseBatteryInverter):
                    raise ProgrammingError(f'only battery inverters can have their power levels set for now: {inv_name}',
                                           source='BaseController')

                n_phases = len(PBSapp_phases.get_inverter_phases(inv_name))
                PBSsent_total = PBSsent * n_phases

                if PBSsent_total == 0:
                    self.log.info(f'{phi}: commanding {inv_name} to standby at {PBSsent_total:.0f} W')
                elif PBSsent_total < 0:
                    self.log.info(f'{phi}: commanding {inv_name} to charge at {PBSsent_total:.0f} W')
                else:
                    self.log.info(f'{phi}: commanding {inv_name} to discharge/generate at {PBSsent_total:.0f} W')
                try:
                    await inv.set_power(PBSsent_total)
                except Exception as e:
                    # a subsystem that cannot be commanded is left where it is for this cycle
                    self.handle_subsystem_error(inv, 'commanding a power level', e)

    async def _command_PBSsent_solar_inverters(self, PBSapp_phases: PBSapp):
        self.log.info(f'sending power limits to enabled solar inverters:')
        commanded: set[str] = set()
        for phi in SINGLE_PHASES:
            ppm = PBSapp_phases[phi]

            # Next the solar inverters for which we can command an optional limit:
            for inv_name, power_limit in ppm.inv_limit.items():
                if inv_name in commanded:
                    continue
                commanded.add(inv_name)

                inv = self.inverters[inv_name]
                if not isinstance(inv, BaseSolarInverter):
                    raise ProgrammingError(f'only solar inverters can have their power limits set for now: {inv_name}',
                                           source='BaseController')

                n_phases = len(PBSapp_phases.get_inverter_phases(inv_name))
                power_limit_total = power_limit if power_limit is None else power_limit * n_phases

                if power_limit_total is None:
                    self.log.info(f'{phi}: commanding {inv_name} to release power limit')
                elif power_limit_total == 0:
                    self.log.info(f'{phi}: commanding {inv_name} to completely curtail solar generation')
                elif power_limit_total > 0:
                    self.log.info(f'{phi}: commanding {inv_name} to curtail solar generation at {power_limit_total:.0f} W')
                else: # negative power limit does not make sense
                    self.log.error(f'{phi}: ignoring negative power limit for solar inverter {inv_name}')
                    continue
                try:
                    await inv.set_power_limit(power_limit_total)
                except Exception as e:
                    # a subsystem that cannot be commanded is left where it is for this cycle
                    self.handle_subsystem_error(inv, 'commanding a power limit', e)

    # def _may_absorb(self, inv: BaseBatteryInverter) -> bool:
    #     '''True when a battery inverter may be charged to absorb surplus solar generation (issue #31). Its state of
    #     charge must be known and below the configured max, so absorbing can never push it past the
    #     state-of-charge limits of issue #7. A battery whose SoC cannot be read is left out: without it there
    #     is no way to tell whether there is any room left to charge into.
    #     '''
    #     stats = self.stats.battery_inverters.get(inv.name)
    #     soc = stats.battery.battery_charge_pct if stats is not None else None
    #     return soc is not None and soc < inv.charge_max_pct

    # def _absorbable_surplus(self, PBSapp: PhasePowerMap, PBSnow: PhasePowerMap, PGnow: float, PGmax_export: float) -> float:
    #     '''Power (W) the battery inverters of a phase can absorb without pulling anything out of the grid
    #     (issue #31): the amount by which the grid connection would carry more than the export ceiling if the
    #     batteries were idle. Everything the batteries take beyond this comes out of the grid rather than out
    #     of a local surplus. calc_PBSsent passes the export ceiling minus the guard it keeps below it: at a
    #     positive price that only lowers the export, at a negative price (ceiling 0) it may draw the guard from
    #     the grid, which is paid for.

    #     This is deliberately built from measurements only (what the meter reads now, minus what the batteries
    #     are drawing or supplying), never from PBSapp: the commanded solar setpoint is the inverter's per-phase
    #     maximum and not what it actually generates (see Mode4Controller.get_PBSapp), so charging on the
    #     strength of that number would have the batteries absorbing solar power that is not there. Taking the
    #     meter reading also keeps the answer right when the solar inverter itself cannot be read: its power is
    #     then part of what the rest of the installation appears to do, but it still shows up at the meter.

    #     The one exception is a solar inverter that runs at the cap it currently has (see _solar_at_cap): the
    #     meter then only shows what the cap lets through, and never what the sun could deliver on top of it.
    #     Going by the meter alone, a battery that gets room to charge while the solar is capped would never
    #     start absorbing, and the solar would stay curtailed for as long as the sun is out. The potential of
    #     such an inverter (up to its ceiling in PBSapp) is therefore counted as surplus as well, and the cap is
    #     raised by whatever the batteries take (see _cap_solar_to_headroom). If the sun cannot deliver it, the
    #     batteries draw the difference from the grid for a single cycle: the inverter then generates below its
    #     new cap, and the next cycle goes by the measurement again.
    #     '''
    #     battery_names = { inv.name for inv in self.battery_inverters }

    #     # compute battery_now: net power of all batteries connected to this phase (positive = net discharging)
    #     battery_now = sum(p for inv_name, p in PBSnow.inv_power.items() if inv_name in battery_names)

    #     # what the solar inverters held back by their cap could generate on top of what they do now
    #     capped_potential = sum(
    #         max(0.0, p - PBSnow.inv_power[inv_name])
    #         for inv_name, p in PBSapp.inv_power.items()
    #         if inv_name in PBSnow.inv_power and self._solar_at_cap(inv_name, PBSnow.inv_power[inv_name])
    #     )
    #     return max(0.0, (PGnow - battery_now + capped_potential) - PGmax_export)

    # def _battery_power_floors(self, PBSapp: PhasePowerMap, absorbable_w: float) -> list[tuple[str, float]]:
    #     '''The battery inverters of a phase, in the order they are to be used to bring its net power down, each
    #     with the lowest power level (W) it may be taken to (issue #31).

    #     A battery can be taken down from PBSapp all the way to its charge limit: a discharging battery first
    #     stops discharging and then starts charging, which keeps the energy in the system. How far below zero
    #     the batteries may go together is bounded by absorbable_w, so never more is charged than the surplus
    #     that is actually measured. A battery that may not absorb (see _may_absorb) is only taken down to
    #     standby: it can stop discharging, but not start charging. The solar inverters are not part of this:
    #     they are only curtailed as a last resort, see calc_PBSsent (issue #29).
    #     '''
    #     floors: list[tuple[str, float]] = []

    #     absorbable = absorbable_w
    #     for inv in self.battery_inverters:
    #         if inv.name not in PBSapp.inv_power:
    #             continue

    #         # negative (charging) floor, bounded by the surplus that is left for this battery to absorb
    #         floor = max(inv.power_limits_phase[0], -absorbable) if self._may_absorb(inv) else 0.0
    #         floors.append((inv.name, floor))
    #         absorbable = max(0.0, absorbable + floor)  # floor <= 0: this battery's share is spoken for

    #     return floors

    # def _solar_generation(self, PBSapp: PhasePowerMap, PBSnow: PhasePowerMap) -> dict[str, float]:
    #     '''Present generation (W) of each solar inverter of a phase, within [0, its ceiling in PBSapp]. A solar
    #     inverter that could not be read is taken at its ceiling (worst case).
    #     '''
    #     return {
    #         i: c if PBSnow.inv_power.get(i) is None else min(c, max(0.0, PBSnow.inv_power[i]))
    #         for i, c in PBSapp.inv_power.items()
    #         if isinstance(self.inverters[i], BaseSolarInverter)
    #     }

    # def _solar_room(self, PBSapp: PhasePowerMap, PBSnow: PhasePowerMap) -> dict[str, float]:
    #     '''Room (W) each solar inverter of a phase is to be given above its present generation when its cap
    #     binds (see _cap_solar_to_headroom): enough to tell it apart from an inverter held back by its cap, and
    #     never beyond its ceiling.
    #     '''
    #     return {
    #         i: min(PBSapp.inv_power[i] - g, max(SOLAR_ROOM_W, g * SOLAR_ROOM_PCT / 100))
    #         for i, g in self._solar_generation(PBSapp, PBSnow).items()
    #     }

    # def _cap_solar_to_headroom(self, PBSsent: PhasePowerMap, PBSnow: PhasePowerMap, PBSlim_max: float) -> None:
    #     '''Cap the solar inverters of a phase to the export headroom that is left once the battery inverters
    #     have been commanded: PBSlim_max minus their PBSsent (issues #29, #31). Whatever the sun delivers, the
    #     solar inverters together can then not push the phase past the export limit - also not when the sun
    #     comes out between two control cycles. The cap only binds when the ceilings (PBSsent on entry) of the
    #     solar inverters together exceed the headroom, and then never below what they generate now as long as
    #     the headroom allows.

    #     The headroom is shared out on what each inverter generates rather than on its ceiling, so an inverter
    #     in the shade (eg. an east-facing array in the afternoon) does not take up room that one in full sun
    #     could have used. On top of its present generation each inverter first gets its room (_solar_room),
    #     so it can show whether the sun delivers more. What is left goes to the inverters that are held back
    #     by their cap (_solar_at_cap) - they are the ones known to be able to use it - and only then to the
    #     others, in both cases in proportion to how far each is below its ceiling. When there is not even room
    #     for the present generation, the inverters are cut back in proportion to it.
    #     '''
    #     ceiling = { i: p for i, p in PBSsent.inv_power.items() if isinstance(self.inverters[i], BaseSolarInverter) }
    #     headroom = max(0.0, PBSlim_max - sum(p for i, p in PBSsent.inv_power.items() if i not in ceiling))
    #     if sum(ceiling.values()) <= headroom:
    #         return  # every solar inverter fits at its ceiling: nothing to cap

    #     ceilings = PhasePowerMap(PBSsent.phase, ceiling)
    #     cap = self._solar_generation(ceilings, PBSnow)
    #     slack = headroom - sum(cap.values())
    #     if slack < 0:
    #         # not even room for the present generation: cut back in proportion to it
    #         total = sum(cap.values())
    #         cap = { i: g * headroom / total for i, g in cap.items() } if total > 0 else { i: 0.0 for i in cap }
    #         slack = 0.0

    #     def share_out(names: list[str], amount: float) -> float:
    #         '''Share amount out over names in proportion to how far each is below its ceiling. Returns the rest.'''
    #         below = { i: ceiling[i] - cap[i] for i in names if ceiling[i] - cap[i] > 0 }
    #         if amount <= 0 or not below:
    #             return amount
    #         given = min(amount, sum(below.values()))
    #         for i, b in below.items():
    #             cap[i] += given * b / sum(below.values())
    #         return amount - given

    #     # first the room of every inverter, then the held-back inverters, then all of them
    #     room = self._solar_room(ceilings, PBSnow)
    #     k = min(1.0, slack / sum(room.values())) if sum(room.values()) > 0 else 0.0
    #     for i, r in room.items():
    #         cap[i] += r * k
    #     slack -= sum(room.values()) * k
    #     held_back = [ i for i in cap if self._solar_at_cap(i, PBSnow.inv_power.get(i)) ]
    #     slack = share_out(held_back, slack)
    #     share_out(list(cap), slack)

    #     for inv_name, c in cap.items():
    #         PBSsent.inv_power[inv_name] = c

    def handle_status(self, request):
        return web.json_response({
            'status': 'ok',
            'running': self.running,
            'mode': self.mode.value,
            'running_start': self.stats.start_ts,
            'stats': self.stats.serialize(),
            'prices': None,
            'schedule': None,
            'schedule_ts': None,
        })

    async def send_ha_notification(self, title: str, message: str):
        # prime method: use the SUPERVISOR_TOKEN (only available in production setup)
        token = os.environ.get('SUPERVISOR_TOKEN')
        url = 'http://supervisor/core/api/services/notify/persistent_notification'
        if not token:
            self.log.info(f'SUPERVISOR_TOKEN unavailable: falling back to manually created token')
            token = self.config.get_general_config()['supervisor_token']
            url = 'http://homeassistant:8123/api/services/notify/persistent_notification'

            if not token:
                self.log.error(f'No long-lived access token defined: unable to send push notification')
                return

        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={'title': title, 'message': message}, headers=headers)

        except Exception as e:
            self.log.error(f'unable to send HA notification: {e}')
