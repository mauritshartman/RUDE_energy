from abc import ABC, abstractmethod
import asyncio
import math
import time
from datetime import datetime as dt
from typing import Optional
from zoneinfo import ZoneInfo
import os

from aiohttp import web
import aiohttp

from config import DoeMaarWattConfig, ControlMode
from common import Logger, Phase, ProgrammingError, PBSapp, PhasePowerMap, SINGLE_PHASES, BaseInverter, DMWException
from stats import ControllerStats
from subsystems.battery_inverters import BaseBatteryInverter, create_battery_inverter
from subsystems.solar_inverters import BaseSolarInverter, create_solar_inverter
from subsystems.energy_meters import BaseEnergyMeter, create_energy_meter, EnergyMeterStats


RECONNECT_DELAY = 10 # seconds before attempting a reconnect
LOOP_DELAY = 10 # control loop delay


class BaseController(ABC):
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        self.config = cfg
        self.log = log

        self.running = False
        self._stats = ControllerStats(cfg)
        self._inv_control = {}

        # set up by setup()
        self.battery_inverters: list[BaseBatteryInverter] = []
        self.solar_inverters: list[BaseSolarInverter] = []
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
        self._stats.reset()

    async def reconnect_delay(self):
        if self.running:
            await asyncio.sleep(RECONNECT_DELAY)

    async def loop_delay(self):
        await asyncio.sleep(self.config.get_general_config().get('loop_delay', LOOP_DELAY))

    def setup(self) -> None:
        bat_inv_cfg = self.config.get_battery_inverters_config()
        sol_inv_cfg = self.config.get_solar_inverters_config()
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

        for inv in self.battery_inverters + self.solar_inverters:
            if inv.name in self.inverters:
                raise ProgrammingError(f'inverters should have a unique name: {inv.name}', source='base_controller')
            self.inverters[inv.name] = inv

        self.inv_phase_map = {
            phase: [
                i.name for i in self.battery_inverters + self.solar_inverters
                if i.connected_phase == phase or i.connected_phase == Phase.ALL
            ]
            for phase in SINGLE_PHASES
        }

        self.energy_meter = create_energy_meter(em_cfg, self.log) if len(em_cfg) > 0 else None

        self.tz = ZoneInfo(self.config.timezone)

    async def connect_subsystems(self):
        await asyncio.gather(*[inv.connect() for inv in self.battery_inverters + self.solar_inverters])

        if self.energy_meter:
            await self.energy_meter.connect()

        self.log.info(f'(re)connected to all subsystems')

    def close_subsystems(self):
        for inv in self.battery_inverters:
            inv.close()
        for inv in self.solar_inverters:
            inv.close()
        if self.energy_meter:
            self.energy_meter.close()
        self.log.info('disconnected from all subsystems')

    async def run(self) -> None:
        '''Run this controller. This entails calling its setup() method and then awaiting its loop() method
        '''
        self.running = True
        self._stats.start_ts = time.time()

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
        if self.battery_inverters:
            bat_inv_stats = await asyncio.gather(*[inv.read_stats() for inv in self.battery_inverters])
            self._stats.battery_inverters = { inv.name: inv_stats for inv, inv_stats in zip(self.battery_inverters, bat_inv_stats) }

        if self.solar_inverters:
            sol_inv_stats = await asyncio.gather(*[inv.read_stats() for inv in self.solar_inverters])
            self._stats.solar_inverters = { inv.name: inv_stats for inv, inv_stats in zip(self.solar_inverters, sol_inv_stats) }

        if self.energy_meter is not None:
            em_stats = await self.energy_meter.read_stats()
            self._stats.energy_meter = em_stats

    async def command_PBSsent(self, now: dt) -> None:
        self._inv_control = {} # reset statistics for inverter control:

        self.log.info(f'computing safe charge/discharge amount (PBsent) for each phase:')
        assert isinstance(self._stats.energy_meter, EnergyMeterStats)

        PBSapp_phases = self.get_PBSapp(now)
        export_limit = self.get_export_limit(now)  # per-phase export ceiling (None = main-fuse limit)

        # first iteration: compute a safe power level for each inverter across each of the three phases
        PBSsent_phases: dict[Phase, PhasePowerMap] = {}
        for phi in SINGLE_PHASES:
            PBSapp = PBSapp_phases[phi]

            PGnow = self._stats.energy_meter.grid[phi].power # type: ignore | negative value: drawing power from the grid
            VGnow = self._stats.energy_meter.grid[phi].voltage # type: ignore
            Imax =  self._stats.energy_meter.max_fuse_a # type: ignore | eg. 25A main fuse
            if PGnow is None or VGnow is None or Imax is None:
                raise ProgrammingError(f'missing grid measurements for {phi}. PGnow: {PGnow}, VGnow: {VGnow}, Imax: {Imax}',
                                       source='calc_PBSsent')

            PBSnow = self._stats.get_PBSnow(phi)
            PBSsent_phases[phi] = self.calc_PBSsent(phi, PBSapp, PBSnow, PGnow, VGnow, Imax, export_limit)

        # second iteration: ensure inverters that are connected to multiple phases, command the same, safest power level
        for inv_name in PBSapp_phases.get_multiphase_inverters():
            phases = PBSapp_phases.get_inverter_phases(inv_name)
            powers = [PBSsent_phases[phi].inv_power[inv_name] for phi in phases]
            if not all(math.isclose(p, powers[0], abs_tol=0.5) for p in powers):
                self.log.info(
                    f'multiphase inverter {inv_name} has inconsistent PBsent across '
                    f'{[p.value for p in phases]}: {[round(p) for p in powers]} W'
                )

            # reconcile to the safest (smallest magnitude) level so the inverter is commanded
            # a single value that stays within every connected phase's grid limit
            safe_power = min(powers, key=abs)
            for phi in phases:
                PBSsent_phases[phi].inv_power[inv_name] = safe_power

        # final iteration: command each inverter exactly once. PBSsent values are per-phase, but set_power
        # expects the total across all connected phases, so scale by the number of phases the inverter spans
        # (1 for single-phase battery/solar inverters, 3 for an inverter connected to ALL phases).
        self.log.info(f'sending charge/discharge amount (PBSsent) to enabled inverters:')
        commanded: set[str] = set()
        for phi, ppm in PBSsent_phases.items():
            for inv_name, PBSsent in ppm.inv_power.items():
                if inv_name in commanded:
                    continue
                commanded.add(inv_name)

                n_phases = len(PBSapp_phases.get_inverter_phases(inv_name))
                PBSsent_total = PBSsent * n_phases

                if PBSsent_total == 0:
                    self.log.info(f'{phi}: commanding {inv_name} to standby at {PBSsent_total:.0f} W')
                elif PBSsent_total < 0:
                    self.log.info(f'{phi}: commanding {inv_name} to charge at {PBSsent_total:.0f} W')
                else:
                    self.log.info(f'{phi}: commanding {inv_name} to discharge/generate at {PBSsent_total:.0f} W')
                await self.inverters[inv_name].set_power(PBSsent_total)

    def calc_PBSsent(self,
        phase: Phase,
        PBSapp: PhasePowerMap,
        PBSnow: PhasePowerMap,
        PGnow: float,
        VGnow: float,
        Imax: float,
        export_limit_w: Optional[float] = None,
    ) -> PhasePowerMap:
        '''Calculate safe charge/discharge amount (PBSsent) based on desired (PBSapp) amount for each inverter,
        in the current system context.

        Parameters:
        -----------
        PBSapp: PhasePowerMap
            Desired charge (negative) or discharge (positive) amount in W for each inverter
        PBSnow: PhasePowerMap
            Power at the battery inverter. Can be negative (charging the battery) or positive (discharging)
        PGnow: float
            Power at grid connection. Can be negative (drawing power from grid) or positive (supplying power)
        VGnow: float
            Measured voltage at grid connection point. Alway a positive value
        Imax: float
            Main fuse current limit at grid connection. Always a positive value
        export_limit_w: Optional[float]
            Optional per-phase ceiling (W) on power exported to the grid, tighter than the main fuse. Used
            e.g. during negative prices to curtail exporting generation to zero while still allowing solar to
            be self-consumed (feeding the house or charging the battery). None uses the fuse limit.

        Returns:
        --------
        PhasePowerMap
            The safe charge / discharge amount (PBSsent) that can be commanded to each inverter
        '''
        assert isinstance(PBSapp, PhasePowerMap)
        assert isinstance(PBSnow, PhasePowerMap)

        if PGnow is None or VGnow is None or Imax is None:
            raise ProgrammingError(f'missing grid measurements. PGnow: {PGnow}, VGnow: {VGnow}, Imax: {Imax}', source='calc_PBSsent')

        PGmax = abs(VGnow * Imax) # main-fuse limit: max power that can flow through the grid connection
        PGmin = -1 * PGmax # Maximum power that can safely be drawn from the grid (negative value)
        # The export ceiling can be tightened below the fuse limit (e.g. to 0 during negative prices) so surplus
        # generation is curtailed rather than exported. The import floor always stays at the fuse limit, so
        # battery charging (drawing from grid or absorbing solar) is never throttled by this cap.
        PGmax_export = PGmax if export_limit_w is None else min(PGmax, export_limit_w)
        Pother = PGnow - PBSnow.net_power  # Power consumed (negative value) or generated (positive) elsewhere in the system (eg. heat pump)
        PBSlim_min = PGmin - Pother # lower limit for net power of all controlled inverters (negative value -> consuming power)
        PBSlim_max = PGmax_export - Pother # upper limit for net power of all controlled inverters (positive value -> generating power)

        # add prelim stats:
        self._inv_control[phase] = {
            'PGnow': PGnow, 'VGnow': VGnow, 'Imax': Imax,
            'PGmin': PGmin, 'PGmax': PGmax, 'Pother': Pother,
            'PBlim_min': PBSlim_min, 'PBlim_max': PBSlim_max,
        }

        PBSapp_net_power = PBSapp.net_power
        PBSsent = PBSapp.copy()
        if PBSlim_min <= PBSapp_net_power and PBSapp_net_power <= PBSlim_max:
            # Combined desired power level for all inverters of this phase falls within the safe range
            return PBSsent

        if PBSapp_net_power < PBSlim_min:
            # The desired net power of all inverters would require more charging than the main grid fuse can handle
            power_exceeded = PBSlim_min - PBSapp_net_power # strictly positive

            # Solution: check for inverters in PBSapp with a negative power level (ie. charging battery inverters) and
            # check if we can be within the limit by reducing their charge level
            charging_inverters = { i: p for i, p in PBSapp.inv_power.items() if p < 0 }
            tot_charge_power = abs(sum(charging_inverters.values()))
            if power_exceeded <= tot_charge_power: # yes
                # modify PBSsent by distributing power_exceeded over the charging inverters,
                # weighted on their original PBSapp charging level
                for inv_name, inv_PBSapp in charging_inverters.items():
                    power_reduction = abs(inv_PBSapp) / tot_charge_power * power_exceeded # strictly positive
                    PBSsent.inv_power[inv_name] = inv_PBSapp + power_reduction

                return PBSsent

            # For now no other viable solutions. Increasing power levels on solar inverters does not guarantee that they generate
            # more power (you cannot command the sun). Also flipping a battery inverter from charging to discharging feels unsafe
            # as that battery inverter might still be charging on a different phase
            raise DMWException(f'insufficient control authority for safe PBSsent power: {PBSapp} < {PBSlim_min}', source='calc_PBSsent')

        if PBSapp_net_power > PBSlim_max:
            # The desired net power of all inverters would supply more power to the main grid than its fuse can handle
            power_exceeded = PBSapp_net_power - PBSlim_max # strictly positive

            # Solution: reduce inverters in PBSapp with a positive power level (ie. solar generation and
            # discharging battery inverters) until we are within the limit. Curtail solar inverters FIRST so
            # the scheduled battery discharge is preserved for as long as possible (only reducing battery
            # discharge once all solar generation has been fully curtailed).
            generating_inverters = { i: p for i, p in PBSapp.inv_power.items() if p > 0 }
            tot_generated_power = sum(generating_inverters.values())  # all positive
            if power_exceeded <= tot_generated_power: # can be resolved by curtailing generation
                solar_names = { inv.name for inv in self.solar_inverters }
                # solar inverters first (sort key False < True), then battery discharge:
                ordered = sorted(generating_inverters.items(), key=lambda kv: kv[0] not in solar_names)
                remaining = power_exceeded
                for inv_name, inv_PBSapp in ordered:
                    if remaining <= 0:
                        break
                    reduction = min(inv_PBSapp, remaining)  # never push a source below zero
                    PBSsent.inv_power[inv_name] = inv_PBSapp - reduction
                    remaining -= reduction

                return PBSsent

            # For now no other viable solutions.
            raise DMWException(f'insufficient control authority for safe PBSsent power: {PBSapp} > {PBSlim_max}', source='calc_PBSsent')

        raise ProgrammingError(f'should not reach here', source='calc_PBSsent')

    def handle_status(self, request):
        return web.json_response({
            'status': 'ok',
            'running': self.running,
            'mode': self.mode.value,
            'running_start': self._stats.start_ts,
            'stats': self._stats.serialize(),
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
