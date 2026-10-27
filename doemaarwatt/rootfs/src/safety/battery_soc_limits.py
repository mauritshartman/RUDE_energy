from typing import Optional

from common import PBSapp, ProgrammingError, Logger
from stats import ControllerStats
from subsystems.battery_inverters import BaseBatteryInverter


# State-of-charge limit handling (issue #7): at a limit the battery trickles a small fixed power to stay
# awake (instead of idling), and oscillates within a small band on the safe side of the limit so it can hold
# there indefinitely without ever crossing the configured max/min.
SOC_TRICKLE_W = 50.0            # magnitude of the standby trickle commanded at a SoC limit
SOC_OSCILLATION_BAND_PCT = 3.0  # width (%) of the band the battery oscillates in, inside the limit


DESCRIPTION_BatterySoCLimitsMixin = '''
Ensure that each battery inverter is kept within its configured state-of-charge limits.
When the controller would charge or discharge a battery that is already at the limit,
a small trickle charge is applied instead.
'''


class BatterySoCLimitsMixin:
    # per-inverter state for the SoC limit oscillation (issue #7):
    _BatterySoCLimitsMixin_soc_hold: dict[str, Optional[str]] = {}   # inverter name -> None | 'max' | 'min'
    _BatterySoCLimitsMixin_trickle_dir: dict[str, int] = {}          # inverter name -> +1 (discharge) / -1 (charge)

    def ensure_battery_soc_limits(self, PBSapp_phases: PBSapp, **kwargs) -> None:
        '''
        Keep each battery inverter within its configured state-of-charge limits (issue #7). Runs for every
        controlling mode as part of the shared PBapp -> PBsent computation, so the limits hold regardless of
        mode.

        When the controller would charge a battery that is already at its max SoC (or discharge one at its min),
        the big charge/discharge is replaced with a small fixed trickle (SOC_TRICKLE_W) so the inverter stays
        awake instead of idling. The battery then oscillates within a small band just inside the limit
        (SOC_OSCILLATION_BAND_PCT), so it can hold there indefinitely without ever crossing the configured
        max/min. As soon as the controller wants to move the battery away from the limit again (e.g. discharge
        a full battery), normal operation resumes.

        The current SoC is taken from the latest stats (populated by get_stats() earlier in the control loop);
        a battery with unknown SoC (e.g. disconnected) is left unchanged.
        '''
        if not isinstance(PBSapp_phases, PBSapp):
            raise ProgrammingError(f'passed argument is not an PBSapp instance', source='BatterySoCLimitsMixin')
        if not hasattr(self, 'battery_inverters'):
            raise ProgrammingError(f'missing battery_inverters attribute', source='BatterySoCLimitsMixin')
        if not hasattr(self, 'stats'):
            raise ProgrammingError(f'missing stats attribute', source='BatterySoCLimitsMixin')
        if not hasattr(self, 'log'):
            raise ProgrammingError(f'missing log attribute', source='BatterySoCLimitsMixin')
        battery_inverters: list[BaseBatteryInverter] = getattr(self, 'battery_inverters')
        all_stats: ControllerStats = getattr(self, 'stats')
        log: Logger = getattr(self, 'log')

        for inv in battery_inverters:
            stats = all_stats.battery_inverters.get(inv.name)
            soc = stats.battery.battery_charge_pct if stats is not None else None
            phases = PBSapp_phases.get_inverter_phases(inv.name)
            if soc is None or not phases:
                self._BatterySoCLimitsMixin_soc_hold[inv.name] = None  # cannot enforce a limit; drop any hold state
                continue

            # batteries are single-phase, so the desired power is the same on each connected phase
            desired = PBSapp_phases[phases[0]].inv_power[inv.name]
            trickle = self.__BatterySoCLimitsMixin_soc_trickle_power(inv, soc, desired)
            if trickle is not None:
                for phi in phases:
                    PBSapp_phases[phi].inv_power[inv.name] = trickle
                action = 'discharge' if trickle > 0 else 'charge'
                log.info(f'ensure_battery_soc_limits: {inv.name} SoC {soc:.0f}% at '
                         f'{self._BatterySoCLimitsMixin_soc_hold[inv.name]} limit, '
                         f'trickle-{action} at {trickle:+.0f} W')

    def __BatterySoCLimitsMixin_soc_trickle_power(self,
        inv: BaseBatteryInverter,
        soc: float,
        desired: float,
    ) -> Optional[float]:
        '''Return the trickle power (W) to command for an inverter that is being held at a SoC limit, or None
        to leave the desired power unchanged. Maintains a small hysteresis oscillation just inside the limit:
        near the max the battery cycles within [max - band, max]; near the min within [min, min + band].
        Sign convention: negative = charging, positive = discharging.
        '''
        name = inv.name
        mx, mn = inv.charge_max_pct, inv.charge_min_pct
        band = SOC_OSCILLATION_BAND_PCT
        hold = self._BatterySoCLimitsMixin_soc_hold.get(name)

        # (re)enter a hold when the controller pushes further into a limit
        if soc >= mx and desired < 0:      # at/above max and still trying to charge
            hold = 'max'
        elif soc <= mn and desired > 0:    # at/below min and still trying to discharge
            hold = 'min'

        power: Optional[float] = None
        if hold == 'max':
            if desired > 0:                # controller now wants to discharge: release, let it move away
                hold = None
            else:                          # oscillate within [max - band, max]
                d = self._BatterySoCLimitsMixin_trickle_dir.get(name, +1)   # start by trickle-discharging down into the band
                if soc <= mx - band:
                    d = -1                 # bottom of band: trickle-charge back up
                elif soc >= mx:
                    d = +1                 # top of band: trickle-discharge back down
                self._BatterySoCLimitsMixin_trickle_dir[name] = d
                power = d * SOC_TRICKLE_W
        elif hold == 'min':
            if desired < 0:                # controller now wants to charge: release
                hold = None
            else:                          # oscillate within [min, min + band]
                d = self._BatterySoCLimitsMixin_trickle_dir.get(name, -1)   # start by trickle-charging up into the band
                if soc >= mn + band:
                    d = +1                 # top of band: trickle-discharge back down
                elif soc <= mn:
                    d = -1                 # bottom of band: trickle-charge back up
                self._BatterySoCLimitsMixin_trickle_dir[name] = d
                power = d * SOC_TRICKLE_W

        self._BatterySoCLimitsMixin_soc_hold[name] = hold
        return power
