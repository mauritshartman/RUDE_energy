import asyncio
import math
from datetime import datetime
from typing import Any, Optional
import random

from common import Logger, ControlStatus, Phase, SPCStats, ProgrammingError, ControlException
from .base import BaseSolarInverter, SolarInverterStats


IO_LATENCY = 0.1  # simulated IO delay

PEAK_POWER_W = 10_000.0  # peak output per phase at solar noon
SUNRISE_H = 6.5           # 06:30 local time
SUNSET_H  = 20.5          # 20:30 local time
SOLAR_NOON_H = 13.0       # hour of peak irradiance


def _solar_power(peak_w: float) -> float:
    """Return simulated solar output (W) for the current wall-clock time using a half-sine curve."""
    now = datetime.now()
    h = now.hour + now.minute / 60.0 + now.second / 3600.0

    if h <= SUNRISE_H or h >= SUNSET_H:
        return 0.0

    # normalise to [0, 1] inside the daylight window, peaking at SOLAR_NOON_H
    day_len = SUNSET_H - SUNRISE_H
    t = (h - SUNRISE_H) / day_len  # 0 → 1 across the day
    power = peak_w * math.sin(math.pi * t)

    # ±3 % random jitter
    power *= random.uniform(0.97, 1.03)
    return max(0.0, power)


class SimSolarInverter(BaseSolarInverter):

    def __init__(self,
        name: str,
        connected_phase: Phase,
        log: Logger,
    ) -> None:
        super().__init__(name, connected_phase, log)

        self.is_connected = False
        self.is_controlled = False

        # External curtailment cap in W (total across all connected phases):
        #   None -> no cap applied, the inverter runs at its natural output
        #   0    -> full curtailment (zero output)
        #   x    -> output capped at x W
        self.power_setpoint: Optional[float] = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any], log: Logger) -> 'SimSolarInverter':
        return cls(
            name=cfg.get('name', 'Simulated 30kW Solar Inverter'),
            connected_phase=cfg.get('connected_phase', Phase.ALL),
            log=log,
        )

    @property
    def power_limits_phase(self) -> tuple[float, float]:
        return (
            0.0, # solar inverter can only source power, not sink it
            PEAK_POWER_W,
        )

    async def _io_delay(self):
        await asyncio.sleep(random.uniform(0.9 * IO_LATENCY, 1.1 * IO_LATENCY))

    async def connect(self) -> None:
        await self._io_delay()

        self.is_connected = True

    def close(self) -> None:
        self.is_connected = False
        self.is_controlled = False

    async def enable_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to assert control, not connected', source=self.name)

        self.is_controlled = True

    async def relinquish_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to relinquish control, not connected', source=self.name)

        self.is_controlled = False
        self.power_setpoint = None  # relinquish external control: inverter runs freely again

    async def read_stats(self) -> SolarInverterStats:
        await self._io_delay()

        # natural (uncurtailed) output the array could deliver on each connected phase right now
        natural = _solar_power(PEAK_POWER_W)

        if self.connected_phase.is_single_phase:
            # No cap (None) -> run at natural output; otherwise the setpoint caps this phase (0 -> zero output).
            phase_cap = natural if self.power_setpoint is None else self.power_setpoint
            phase_power = { self.connected_phase: min(natural, phase_cap) }
            total = sum(phase_power.values())

            self.log.debug(f'{self.name}: {self.connected_phase}={phase_power[self.connected_phase]:.0f} W')

        else: # tri-phase connected: the setpoint is a total, split evenly across the three phases
            phase_cap = natural if self.power_setpoint is None else self.power_setpoint / 3
            phase_limit = min(natural, phase_cap) # max power per phase
            phase_power = { Phase.L1: phase_limit, Phase.L2: phase_limit, Phase.L3: phase_limit }
            total = sum(phase_power.values())

            self.log.debug(f'{self.name}: ' + ' '.join(f'{phi}={pwr:.0f} W' for phi, pwr in phase_power.items()) + f' {total:.0f} W')

        return SolarInverterStats(
            control_status=ControlStatus.NOMINAL if self.is_connected else ControlStatus.UNCONTROLLED,
            setpoint_limit_w=self.power_setpoint,
            total_power_w=total,
            ac_side={ phi: SPCStats(power=phase_pow) for phi, phase_pow in phase_power.items() },
        )

    async def set_power(self, power_w: float) -> None:
        '''Apply a curtailment setpoint capping total output at `power_w` W across all connected
        phases. `power_w == 0` means full curtailment (zero output); the maximum caps at natural output.'''
        if power_w < 0:
            raise ProgrammingError('solar inverter can only source power, not sink it', source=self.name)
        elif power_w > 30_000:
            raise ProgrammingError('exceeds power set point for this solar inverter', source=self.name)

        if not self.is_controlled:
            raise ProgrammingError(f'unable to apply power setpoint: solar inverter not being controlled', source=self.name)

        self.power_setpoint = power_w
