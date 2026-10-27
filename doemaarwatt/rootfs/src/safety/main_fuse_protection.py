from datetime import datetime as dt
import math
from typing import Optional

from common import PBSapp, ProgrammingError, Logger, SINGLE_PHASES, PhasePowerMap, Phase, BaseInverter, ControlStatus
from subsystems.battery_inverters import BaseBatteryInverter
from subsystems.solar_inverters import BaseSolarInverter
from stats import ControllerStats


DESCRIPTION_MainFuseProtectionMixin = '''
Ensure the main fuse is protected by limiting current in/out through the main fuse,
for each phase L1, L2 and L3. In case of too much current, power to devices is reduced
in order of inverter category: battery inverters first, then solar inverters and EV chargers
last.
'''

# Tolerance (W) on the grid limits. PGnow comes from the energy meter and the inverter power levels from the
# inverters themselves, read a moment apart, and Pother is what remains after subtracting the one from the
# other - so the projection carries the error of every reading that went into it. A limit missed by less than
# this is measurement noise rather than a fuse about to go: correcting for it achieves nothing, and stopping
# the control loop over it costs far more than it protects. On a 25 A phase 50 W is about 0.2 A.
POWER_TOLERANCE_W = 50.0


class MainFuseProtectionMixin:

    def ensure_main_fuse_protection(self, PBSapp_phases: PBSapp, **kwargs) -> None:
        '''
        Ensure the main fuse is protected by limiting current in/out through the main fuse,
        for each phase L1, L2 and L3. In case of too much current, power to devices is reduced
        in order of inverter category:

        - Capping of battery charging or discharging
        - Capping of solar inverter generation
        - Capping of EV charger charging
        '''
        # ensure parameters and attributes are there:
        if not isinstance(PBSapp_phases, PBSapp):
            raise ProgrammingError(f'passed argument is not an PBSapp instance', source='MainFuseProtectionMixin')
        if 'now' not in kwargs or not isinstance(kwargs['now'], dt):
            raise ProgrammingError(f'ensure_main_fuse_protection requires a keyword parameter now (datetime)', source='MainFuseProtectionMixin')
        if not hasattr(self, 'inverters'):
            raise ProgrammingError(f'missing inverters attribute', source='MainFuseProtectionMixin')
        inverters: dict[str, BaseInverter] = getattr(self, 'inverters')
        if not hasattr(self, 'stats'):
            raise ProgrammingError(f'missing stats attribute', source='MainFuseProtectionMixin')
        if not hasattr(self, 'log'):
            raise ProgrammingError(f'missing log attribute', source='MainFuseProtectionMixin')
        if not hasattr(self, 'get_export_limit'):
            raise ProgrammingError(f'missing get_export_limit method', source='MainFuseProtectionMixin')
        get_export_limit_func = getattr(self, 'get_export_limit')
        if not callable(get_export_limit_func):
            raise ProgrammingError(f'get_export_limit not callable', source='MainFuseProtectionMixin')
        stats: ControllerStats = getattr(self, 'stats')
        log: Logger = getattr(self, 'log')
        export_limit = get_export_limit_func(kwargs['now'])

        # first iteration: ensure main fuse protection for each phase individually:
        for phi in SINGLE_PHASES:
            pbs_app = PBSapp_phases[phi]

            pg_now = stats.energy_meter.grid[phi].power # type: ignore | negative value: drawing power from the grid
            vg_now = stats.energy_meter.grid[phi].voltage # type: ignore
            i_max =  stats.energy_meter.max_fuse_a # type: ignore | eg. 25A main fuse
            if pg_now is None or vg_now is None or i_max is None:
                raise ProgrammingError(f'missing grid measurements for {phi}. PGnow: {pg_now}, VGnow: {vg_now}, Imax: {i_max}',
                                        source='MainFuseProtectionMixin')

            pbs_now = stats.get_PBSnow(phi)
            self._MainFuseProtectionMixin_calculate_safe_PBSapp(
                phi, inverters, pbs_app, pbs_now, pg_now, vg_now, i_max, log, export_limit) # type:ignore

        # second iteration: ensure inverters that are connected to multiple phases, command the same, safest power level
        self._MainFuseProtectionMixin_reconcile_multiphase_inverters(inverters, PBSapp_phases, log)

    def _MainFuseProtectionMixin_reconcile_multiphase_inverters(self,
        inverters: dict[str, BaseInverter],
        pbs_app_phases: PBSapp,
        log: Logger,
    ):
        '''Ensure inverters that are connected to multiple phases, command the same, safest power level or power limit
        '''
        for inv_name in pbs_app_phases.get_multiphase_inverters():
            inv = inverters[inv_name]
            phases = pbs_app_phases.get_inverter_phases(inv_name)

            if isinstance(inv, BaseBatteryInverter):
                powers = [pbs_app_phases[phi].inv_power[inv_name] for phi in phases]
                safe_power = min(powers, key=abs)
                if not all(math.isclose(p, powers[0], abs_tol=0.5) for p in powers):
                    log.info(
                        f'ensure_main_fuse_protection: multiphase inverter {inv_name} has differing PBSapp across '
                        f'{[p.value for p in phases]}: {[round(p) for p in powers]} W.'
                        f'Modifying to safest level: {round(safe_power)} W.'
                    )

                    # reconcile to the safest (smallest magnitude) level so the inverter is commanded
                    # a single value that stays within every connected phase's grid limit
                    for phi in phases:
                        pbs_app_phases[phi].inv_power[inv_name] = safe_power

            elif isinstance(inv, BaseSolarInverter):
                limits = [pbs_app_phases[phi].inv_limit[inv_name] for phi in phases]
                limits = [l for l in limits if l is not None] # filter out None (= no limit) values
                if len(limits) == 0: # no limit for this solar inverter for any of its connected phases
                    continue
                safe_limit = min(limits, key=abs)
                if not all(math.isclose(p, limits[0], abs_tol=0.5) for p in limits):
                    log.info(
                        f'ensure_main_fuse_protection: multiphase inverter {inv_name} has differing power limit across '
                        f'{[p.value for p in phases]}: {[round(p) for p in limits]} W.'
                        f'Limiting to safest level: {round(safe_limit)} W.'
                    )

                    # reconcile to the safest (smallest magnitude) level so the inverter is limited
                    # to a single value that stays within every connected phase's grid limit
                    for phi in phases:
                        pbs_app_phases[phi].inv_limit[inv_name] = safe_limit

            else:
                raise ProgrammingError(f'invalid inverter type in reconciliation loop: {inv_name}', source='MainFuseProtectionMixin')

    def _MainFuseProtectionMixin_calculate_safe_PBSapp(self,
        phase: Phase,
        inverters: dict[str, BaseInverter],
        pbs_app: PhasePowerMap,
        pbs_now: PhasePowerMap,
        pg_now: float,
        vg_now: float,
        i_max: float,
        log: Logger,
        export_limit_w: Optional[float] = None,
    ):
        '''Calculate safe charge/discharge amount (PBSsent) based on desired (PBSapp) amount for each inverter,
        for a particular phase in the current system context.

        Parameters:
        -----------
        pbs_app: PhasePowerMap
            Desired charge (negative) or discharge (positive) amount in W for each inverter connected to this phase
            pbs_app is modified in case its application would exceed the main fuse rating.
        pbs_now: PhasePowerMap
            Current power level of the various inverters. Can be negative (charging/consuming) or positive (discharging/generating)
        pg_now: float
            Power at grid connection. Can be negative (drawing power from grid) or positive (supplying power)
        vg_now: float
            Measured voltage at grid connection point. Alway a positive value
        i_max: float
            Main fuse current limit at grid connection. Always a positive value
        export_limit_w: Optional[float]
            Optional per-phase ceiling (W) on power exported to the grid, tighter than the main fuse. Used
            e.g. during negative prices to curtail exporting generation to zero while still allowing solar to
            be self-consumed (feeding the house or charging the battery): solar is then capped to the export
            headroom. None uses the fuse limit. Either way solar is capped to the headroom below the export
            ceiling, which only binds when the solar could otherwise push the phase past it (issues #29, #31).
        '''
        assert isinstance(pbs_app, PhasePowerMap)
        assert isinstance(pbs_now, PhasePowerMap)

        if pg_now is None or vg_now is None or i_max is None:
            raise ProgrammingError(f'missing grid measurements. PGnow: {pg_now}, VGnow: {vg_now}, Imax: {i_max}', source='MainFuseProtectionMixin')
        if not hasattr(self, 'inv_control'):
            raise ProgrammingError(f'missing inv_control attribute', source='MainFuseProtectionMixin')
        inverters_phase = { n: i for n, i in inverters.items() if i.connected_phase == Phase.ALL or i.connected_phase == phase }
        inv_control: dict = getattr(self, 'inv_control')

        # First, determine the power limits for this phase
        pg_max = abs(vg_now * i_max) # main-fuse limit: max power that can be supplied to the grid connection
        pg_min = -1 * pg_max # Maximum power that can safely be drawn from the grid (negative value)
        # The export ceiling can be tightened below the fuse limit (e.g. to 0 during negative prices) so surplus
        # generation is curtailed rather than exported. The import floor always stays at the fuse limit, so
        # battery charging (drawing from grid or absorbing solar) is never throttled by this cap.
        pg_max_export = pg_max if export_limit_w is None else min(pg_max, export_limit_w)

        # Pother is power consumed (negative value) or generated (positive) elsewhere in the system. This excludes
        # battery and solar inverters since we actively control those. But for now it does include EV car chargers
        # as we do not control those actively. Uncontrolled inverters for which we do not have a reading are also
        # included in Pother
        pbs_now_controlled = sum(
            pbs_now.inv_power.get(n, 0) for n, inv in inverters_phase.items()
            if isinstance(inv, (BaseBatteryInverter, BaseSolarInverter)))
        p_other = pg_now - pbs_now_controlled
        pbs_lim_min = pg_min - p_other # lower limit for net power of all controlled inverters (negative value -> consuming power)
        pbs_lim_max = pg_max_export - p_other # upper limit for net power of all controlled inverters (positive value -> generating power)

        # add prelim stats:
        inv_control[phase] = {
            'PGnow': pg_now, 'VGnow': vg_now, 'Imax': i_max,
            'PGmin': pg_min, 'PGmax': pg_max, 'PGmax_export': pg_max_export, 'Pother': p_other,
            'PBlim_min': pbs_lim_min, 'PBlim_max': pbs_lim_max,
        }

        # Now, make a projection of the power levels that would result from applying pbs_app as-is for this phase.
        # Battery inverters are taken from PBSapp, solar inverters from PBSnow
        pbs_projected = (
            sum(pbs_app.inv_power[n] for n, inv in inverters_phase.items() if isinstance(inv, BaseBatteryInverter)) +
            self._MainFuseProtectionMixin_expected_solar_power(pbs_now, inverters_phase, log)
        )

        if pbs_projected < pbs_lim_min - POWER_TOLERANCE_W: # too much grid import
            self._MainFuseProtectionMixin_reduce_grid_import(phase, pbs_projected, pbs_lim_min, pg_min, p_other,
                                                             pbs_app, inverters_phase, log)
        elif pbs_projected > pbs_lim_max + POWER_TOLERANCE_W: # too much grid export
            self._MainFuseProtectionMixin_reduce_grid_export(phase, pbs_projected, pbs_lim_max, pg_max_export, p_other,
                                                             pbs_app, pbs_now, inverters_phase, log)

    def _MainFuseProtectionMixin_expected_solar_power(self,
        pbs_now: PhasePowerMap,
        inverters: dict[str, BaseInverter],
        log: Logger,
    ) -> float:
        '''Return a the expected solar power. This is the sum of:
        - Current (PBSnow) power levels of solar inverters which have a nominal control status
        - Minimum (closest to zero) of PBSnow (if available), setpoint limit (if set), and power limit of solar inverters which have a
            non-nominal control status
        '''
        ret = 0.0
        for inv_name, inv in inverters.items():
            if not isinstance(inv, BaseSolarInverter):
                continue

            if inv_name not in pbs_now.inv_power: # there must be a reading, even when the sun is not shining
                # Whatever this inverter generates right now is already part of Pother: it shows up in the
                # meter reading, but not in PBSnow, so it never got subtracted. Adding an estimate on top of
                # that would count it twice and invent an overshoot that is not there. Leave it to Pother and
                # assume it stays where it is, which is the assumption Pother carries for everything else on
                # the phase (the EV charger, the house load). The cost is reacting one control loop late when
                # this inverter ramps up, the same delay that applies to any other change in Pother.
                log.error(f'ensure_main_fuse_protection: solar inverter {inv_name} ({inv.get_control_status()}) has no '
                          f'PBSnow power reading - leaving its generation to Pother, so a change in it is noticed a loop late')
                continue

            if inv.get_control_status() == ControlStatus.NOMINAL: # nominal control
                inv_power = pbs_now.inv_power[inv_name]
                if inv_power < 0:
                    log.error(f'ensure_main_fuse_protection: solar inverter {inv_name} has a negative PBSnow power reading - this means it is somehow consuming power')
                else:
                    ret += inv_power

            else: # non-nominal control. Make a safe assumption
                limits = [
                    pbs_now.inv_power[inv_name], # current PBSnow for this phase and solar inverter
                    inv.get_setpoint_limit(), # if a setpoint is set, it is per phase
                    inv.power_limits_phase[1], # upper (= producing) limit
                ]
                ret += min(l for l in limits if l is not None)

        return ret

    def _MainFuseProtectionMixin_headroom(self,
        phase: Phase,
        limit_w: float,
        fuse_limit_w: float,
        p_other: float,
        verb: str,
    ) -> str:
        '''Describe a limit in the terms it is built from: the main fuse of this phase, and everything else
        already drawing from or supplying to it.

        Worth spelling out, because the limit is on the controlled inverters and not on the grid connection.
        A line reading 'reduce grid import to a safe 758W' invites the reading that the grid connection may
        only carry 758W, when the fuse allows 5750W and the other 4992W are simply spoken for already.
        '''
        return (f'{phase}: the controlled inverters may {verb} at most {abs(limit_w):.0f}W '
                f'(main fuse {abs(fuse_limit_w):.0f}W, rest of this phase {p_other:+.0f}W)')

    def _MainFuseProtectionMixin_reduce_grid_import(self,
        phase: Phase,
        pbs_projected: float,
        pbs_lim_min: float,
        pg_min: float,
        p_other: float,
        pbs_app: PhasePowerMap,
        inverters: dict[str, BaseInverter],
        log: Logger,
    ):
        # We need to modify PBSapp as we are projected to consume too much power from the grid. The battery
        # inverters are the only lever: solar inverters cannot be commanded to generate more (you cannot
        # command the sun) and the EV charger is not controlled yet, it sits in Pother.
        # Solution 1: reduce charging levels on any charging battery inverter
        # Solution 2: if that is not enough, stop charging altogether and have the batteries discharge instead
        # NOTE: pbs_projected < pbs_lim_min
        power_exceeded = pbs_lim_min - pbs_projected # positive number
        charging_inverters = { i: p for i, p in pbs_app.inv_power.items() if p < 0 and isinstance(inverters[i], BaseBatteryInverter) }
        tot_charge_power = abs(sum(charging_inverters.values()))
        if power_exceeded <= tot_charge_power:
            # Solution 1: modify PBSapp by distributing power_exceeded over the charging inverters,
            # weighted on their original PBSapp charging level
            headroom = self._MainFuseProtectionMixin_headroom(phase, pbs_lim_min, pg_min, p_other, 'draw')
            log.info(f'ensure_main_fuse_protection: {headroom}, exceeded by {power_exceeded:.0f}W: '
                     f'reducing battery charging (solution 1)')
            for inv_name, inv_pbs_app in charging_inverters.items():
                power_reduction = abs(inv_pbs_app) / tot_charge_power * power_exceeded # strictly positive
                log.info(f'ensure_main_fuse_protection: battery inverter {inv_name} charging levels reduced from '
                            f'{abs(inv_pbs_app):.0f}W to {abs(inv_pbs_app + power_reduction):.0f}W (solution 1)')
                pbs_app.inv_power[inv_name] = inv_pbs_app + power_reduction
            return

        # Solution 2: not charging is not enough, so the batteries have to supply power themselves. This is
        # the case whenever pbs_lim_min is positive: the load on this phase alone is beyond what the main fuse
        # can carry, so the controlled inverters have to deliver the difference to keep the grid current within
        # its rating. Stop all charging first, then discharge as far as the batteries allow
        remaining = power_exceeded
        headroom = self._MainFuseProtectionMixin_headroom(phase, pbs_lim_min, pg_min, p_other, 'draw')
        log.info(f'ensure_main_fuse_protection: {headroom}, exceeded by {power_exceeded:.0f}W: '
                 f'not charging is not enough, applying solution 2')
        for inv_name, inv_pbs_app in charging_inverters.items():
            log.info(f'ensure_main_fuse_protection: stop battery inverter {inv_name} charging of {abs(inv_pbs_app):.0f}W (solution 2)')
            pbs_app.inv_power[inv_name] = 0.0
            remaining -= abs(inv_pbs_app)

        bat_inverters = { n: i for n, i in inverters.items() if isinstance(i, BaseBatteryInverter) }
        additional_discharge_potential = { n: self._MainFuseProtectionMixin_battery_suppliable_power(i, pbs_app)
                                           for n, i in bat_inverters.items() }
        # Worth saying plainly when nothing on this phase can supply anything: the fuse protection then has no
        # actuator here at all, which is a different situation from 'tried and fell short'. It happens when the
        # phase holds no battery inverter, or when the one it holds is not under control - eg. because it is
        # unreachable and configured with ignore_errors
        if not any(potential > 0 for potential in additional_discharge_potential.values()):
            if len(bat_inverters) == 0:
                log.error(f'ensure_main_fuse_protection: {phase} has no battery inverter, so nothing on this '
                          f'phase can be commanded to bring its grid import down')
            else:
                not_supplying = ', '.join(sorted(bat_inverters))
                log.error(f'ensure_main_fuse_protection: no battery inverter on {phase} can supply power '
                          f'({not_supplying}): not under control, or at its state-of-charge limit - the main '
                          f'fuse of this phase cannot be protected by this controller')

        # command each battery to discharge until no remaining needs to be supplied, starting with the inverter
        # that can supply the most: it is the one that can best afford it
        log.info(f'ensure_main_fuse_protection: attempt additional battery discharging to reduce grid import by '
                 f'{remaining:.0f}W (solution 2)')
        for inv_name in sorted(additional_discharge_potential, key=lambda n: additional_discharge_potential[n], reverse=True):
            if remaining <= 0:
                return
            inv_potential = min(additional_discharge_potential[inv_name], remaining) # never overshoot the target
            if inv_potential > 0: # there is potential, so increase discharging of this inverter
                log.info(f'ensure_main_fuse_protection: battery inverter {inv_name} discharging levels increased from '
                         f'{pbs_app.inv_power[inv_name]:.0f}W to {pbs_app.inv_power[inv_name] + inv_potential:.0f}W (solution 2)')
                pbs_app.inv_power[inv_name] += inv_potential # more positive -> more discharging
                remaining -= inv_potential

        if remaining > POWER_TOLERANCE_W:
            # Everything that could be done has been applied to PBSapp above, so what is commanded is as safe as
            # this installation can make it, and what is left is beyond our control: the import is drawn by
            # something we do not command. Report it and carry on, the way the export side does.
            #
            # Deliberately not an exception. A controller that stops here (or falls back to another mode) does
            # not reduce the import by a single watt - the load is the load - and it gives up the next cycle's
            # chance to react, along with everything else it was doing. See the 14:40 log of 2026-10-27, where
            # a 102W overshoot on a phase whose only battery was unreachable ended dynamic scheduling for the day
            log.error(f'ensure_main_fuse_protection: {phase}: the controlled inverters may draw at most '
                      f'{abs(pbs_lim_min):.0f}W (main fuse {abs(pg_min):.0f}W, rest of this phase {p_other:+.0f}W), '
                      f'still exceeded by {remaining:.0f}W after stopping all battery charging '
                      f'({tot_charge_power:.0f}W) and discharging every battery inverter that can supply power')

    def _MainFuseProtectionMixin_reduce_grid_export(self,
        phase: Phase,
        pbs_projected: float,
        pbs_lim_max: float,
        pg_max_export: float,
        p_other: float,
        pbs_app: PhasePowerMap,
        pbs_now: PhasePowerMap,
        inverters: dict[str, BaseInverter],
        log: Logger,
    ):
        bat_inverters = { n: i for n, i in inverters.items() if isinstance(i, BaseBatteryInverter) }

        # We need to modify PBSapp as we are projected to export too much power to the grid.
        # Solution 1: we reduce discharging levels on any discharging battery inverter
        # Solution 2: If that is not sufficient, then we try flipping battery inverters from discharging to charging
        # Solution 3: If that fails too, we curtail solar generation.
        power_exceeded = pbs_projected - pbs_lim_max # positive number
        discharging_bat_inverters = { i: p for i, p in pbs_app.inv_power.items() if p > 0 and i in bat_inverters }
        tot_discharge_power = sum(discharging_bat_inverters.values())
        if power_exceeded <= tot_discharge_power:
            # Solution 1: we reduce discharging batteries by distributing power_exceeded over the
            # discharging inverters, weighted on their original PBSapp discharging level
            headroom = self._MainFuseProtectionMixin_headroom(phase, pbs_lim_max, pg_max_export, p_other, 'supply')
            log.info(f'ensure_main_fuse_protection: {headroom}, exceeded by {power_exceeded:.0f}W: '
                     f'reducing battery discharging (solution 1)')
            for inv_name, inv_pbs_app in discharging_bat_inverters.items():
                power_reduction = abs(inv_pbs_app) / tot_discharge_power * power_exceeded # strictly positive
                log.info(f'ensure_main_fuse_protection: battery inverter {inv_name} discharging levels reduced from '
                            f'{abs(inv_pbs_app)}W to {abs(inv_pbs_app - power_reduction)}W')
                pbs_app.inv_power[inv_name] = inv_pbs_app - power_reduction
            return

        # power exceeded > tot_discharge_power: try solution 2
        remaining = power_exceeded
        headroom = self._MainFuseProtectionMixin_headroom(phase, pbs_lim_max, pg_max_export, p_other, 'supply')
        log.info(f'ensure_main_fuse_protection: {headroom}, exceeded by {power_exceeded:.0f}W: '
                 f'reducing discharging is not enough, applying solution 2')
        for inv_name, p in discharging_bat_inverters.items(): # first set each discharging inverter to standby
            log.info(f'ensure_main_fuse_protection: stop battery inverter {inv_name} discharging of {p}W (solution 2)')
            pbs_app.inv_power[inv_name] = 0.0
            remaining -= p

        # then compute how much (additional) charging power we can assign to each battery inverter for this phase
        additional_charge_potential = { n: self._MainFuseProtectionMixin_battery_absorbable_power(i, pbs_app)
                                for n, i in bat_inverters.items() }
        # command each battery to max charge until no remaining needs to be absorbed, in order of PBSapp
        log.info(f'ensure_main_fuse_protection: attempt additional battery charging to reduce grid export by {power_exceeded}W (solution 2)')
        for inv_name, p in sorted(pbs_app.inv_power.items(), key=lambda item: item[1]): # starting with inverters that were already charging
            if remaining <= 0:
                return
            inv_potential = additional_charge_potential[inv_name]
            if inv_potential > 0: # there is potential, so increase charging of this inverter
                if inv_potential > remaining: # ensure we do not overshoot the target
                    inv_potential = remaining
                log.info(f'ensure_main_fuse_protection: battery inverter {inv_name} charging levels increased from '
                            f'{abs(pbs_app.inv_power[inv_name])}W to {abs(pbs_app.inv_power[inv_name] - inv_potential)}W (solution 2)')
                pbs_app.inv_power[inv_name] -= inv_potential # more negative -> more charging
                remaining -= inv_potential
        if remaining <= 0:
            return

        # still some excessive grid export power remaining, so solution 3 needed: solar curtailment
        # make a conservative estimate of controllable solar power based on PBS_now. If that estimate is higher than
        # the remaining excessive power, apply appropriate power limits to each solar inverter
        log.info(f'ensure_main_fuse_protection: attempt solar curtailment to reduce grid export by {remaining}W (solution 3)')
        controllable_solar_power = {}
        sol_inverters = { n: i for n, i in inverters.items() if isinstance(i, BaseSolarInverter) }
        for inv_name in sol_inverters.keys():
            if inv_name in pbs_now.inv_power:
                controllable_solar_power[inv_name] = pbs_now.inv_power[inv_name]
                log.info(f'ensure_main_fuse_protection: applying curtailment to {inv_name} which was generating at {pbs_now.inv_power[inv_name]}W')
        tot_curtailment_potential = sum(controllable_solar_power.values())
        if tot_curtailment_potential < remaining:
            log.error(f'ensure_main_fuse_protection: total solar curtailment potential: {tot_curtailment_potential}W insufficient - full curtailment')
            for inv_name in sol_inverters.keys():
                pbs_app.inv_limit[inv_name] = 0
        else:
            safe_sol_production = tot_curtailment_potential - remaining # zero or positive
            log.info(f'ensure_main_fuse_protection: curtailing current solar power from {tot_curtailment_potential}W to {safe_sol_production}W')
            for inv_name, cur_p in controllable_solar_power.items():
                inv_limit = abs(cur_p) / tot_curtailment_potential * safe_sol_production
                log.info(f'ensure_main_fuse_protection: solar inverter {inv_name} limited to {inv_limit}W')
                pbs_app.inv_limit[inv_name] = inv_limit

    def _MainFuseProtectionMixin_battery_absorbable_power(self,
        inv: BaseBatteryInverter,
        pbs_app: PhasePowerMap,
    ) -> float:
        '''Returns the amounts of power the given battery inverter can absorb, on top of any charging it might already be doing.
        If it is close to its state of charge limit, or if the control status of the inverter is not nominal this will be zero.
        Otherwise, it will be its charging limit (minus any charging already being planned).

        The amount of power returned will be zero or a positive value, expressed in Watts
        '''
        if not hasattr(self, 'stats'):
            raise ProgrammingError(f'missing stats attribute', source='MainFuseProtectionMixin')
        all_stats: ControllerStats = getattr(self, 'stats')

        control_status = inv.get_control_status()
        stats = all_stats.battery_inverters.get(inv.name)
        soc = stats.battery.battery_charge_pct if stats is not None else None

        if (
            control_status != ControlStatus.NOMINAL or
            soc is None or soc >= inv.charge_max_pct
        ):
            return 0.0

        # in case the inverter is already planned to do some charging, deduct that amount from the charge limit
        if pbs_app.inv_power[inv.name] < 0: # negative, so already charging
            return abs(inv.charge_limit_w) + pbs_app.inv_power[inv.name] # charge limit reduced
        return abs(inv.charge_limit_w) # otherwise just the charge limit

    def _MainFuseProtectionMixin_battery_suppliable_power(self,
        inv: BaseBatteryInverter,
        pbs_app: PhasePowerMap,
    ) -> float:
        '''Returns the amount of power the given battery inverter can supply, on top of any discharging it might
        already be doing. The mirror of _battery_absorbable_power: it is needed when the load on a phase alone
        exceeds the main fuse rating, which no amount of not-charging can fix.
        If it is at or below its state of charge limit, or if the control status of the inverter is not nominal
        this will be zero, so this never discharges a battery past the limits of issue #7.
        Otherwise, it will be its discharging limit (minus any discharging already being planned).

        The amount of power returned will be zero or a positive value, expressed in Watts
        '''
        if not hasattr(self, 'stats'):
            raise ProgrammingError(f'missing stats attribute', source='MainFuseProtectionMixin')
        all_stats: ControllerStats = getattr(self, 'stats')

        control_status = inv.get_control_status()
        stats = all_stats.battery_inverters.get(inv.name)
        soc = stats.battery.battery_charge_pct if stats is not None else None

        if (
            control_status != ControlStatus.NOMINAL or
            soc is None or soc <= inv.charge_min_pct
        ):
            return 0.0

        # in case the inverter is already planned to do some discharging, deduct that from the discharge limit
        already_discharging = max(0.0, pbs_app.inv_power.get(inv.name, 0.0))
        return max(0.0, inv.discharge_limit_w - already_discharging)
