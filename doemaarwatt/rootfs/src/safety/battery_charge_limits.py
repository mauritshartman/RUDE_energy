import math

from common import PBSapp, ProgrammingError, Logger, SINGLE_PHASES
from subsystems.battery_inverters import BaseBatteryInverter


DESCRIPTION_BatteryChargeLimitsMixin = '''
Ensure each battery inverters is never commanded to charge or discharge more than its configured limit.
'''


class BatteryChargeLimitsMixin:

    def ensure_battery_charge_limits(self, PBSapp_phases: PBSapp, **kwargs) -> None:
        '''
        Ensure commanded power levels for each battery inverter are kept within charge/discharge limits.

        The earlier stages of the PBSsent computation mutate PhasePowerMap.inv_power directly (calc_PBSsent
        redistributes a grid-limit overshoot across the charging/generating inverters, and apply_soc_limits
        injects a trickle power). Neither re-applies the per-inverter power limits, so a battery inverter can end
        up commanded outside its configured charge (negative) / discharge (positive) range. Clamp each battery
        inverter's commanded power on every phase it is connected to back into power_limits_phase, which is
        expressed per phase.
        '''
        if not isinstance(PBSapp_phases, PBSapp):
            raise ProgrammingError(f'passed argument is not an PBSapp instance', source='BatterySoCLimitsMixin')
        if not hasattr(self, 'battery_inverters'):
            raise ProgrammingError(f'missing battery_inverters attribute', source='BatteryChargeLimitsMixin')
        if not hasattr(self, 'stats'):
            raise ProgrammingError(f'missing stats attribute', source='BatteryChargeLimitsMixin')
        if not hasattr(self, 'log'):
            raise ProgrammingError(f'missing log attribute', source='BatteryChargeLimitsMixin')
        battery_inverters: list[BaseBatteryInverter] = getattr(self, 'battery_inverters')
        log: Logger = getattr(self, 'log')

        for inv in battery_inverters:
            low, high = inv.power_limits_phase
            for phi in SINGLE_PHASES:
                ppm = PBSapp_phases[phi]
                if ppm is None or inv.name not in ppm.inv_power:
                    continue

                desired = ppm.inv_power[inv.name]
                clamped = inv.apply_power_limits(desired)
                if not math.isclose(desired, clamped, abs_tol=0.5):
                    log.info(f'ensure_battery_charge_limits: clamping {inv.name} {phi} PBSsent from {desired:.0f} W to {clamped:.0f} W '
                             f'to stay within charge/discharge limits [{low:.0f}, {high:.0f}] W')
                    ppm.inv_power[inv.name] = clamped
