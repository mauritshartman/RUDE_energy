import asyncio
import random
from typing import Any

from common import Logger, ControlStatus, Phase, SPCStats
from .base import BaseEnergyMeter, EnergyMeterStats


IO_LATENCY = 0.1  # simulated IO delay


class SimEnergyMeter(BaseEnergyMeter):

    def __init__(self, name: str, max_fuse_a: int, log: Logger) -> None:
        super().__init__(name, max_fuse_a, log)
        self.is_connected = False

    @classmethod
    def from_config(cls, cfg: dict[str, Any], log: Logger) -> 'SimEnergyMeter':
        return cls(
            name=cfg.get('name', 'Simulated Energy Meter'),
            max_fuse_a=cfg.get('max_fuse_current', 25),
            log=log,
        )

    async def _io_delay(self):
        await asyncio.sleep(random.uniform(0.9 * IO_LATENCY, 1.1 * IO_LATENCY))

    async def connect(self) -> None:
        await self._io_delay()
        self.is_connected = True

    def close(self) -> None:
        self.is_connected = False

    async def read_stats(self) -> EnergyMeterStats:
        await self._io_delay()

        voltages = [random.uniform(228.0, 232.0) for _ in range(3)]
        currents = [random.uniform(2.0, 8.0) for _ in range(3)]
        powers   = [-v * c for v, c in zip(voltages, currents)]  # negative = drawing from grid

        return EnergyMeterStats(
            control_status=ControlStatus.NOMINAL if self.is_connected else ControlStatus.UNCONTROLLED,
            max_fuse_a=self.max_fuse_a,
            grid={
                Phase.L1: SPCStats(voltage=voltages[0], current=currents[0], power=powers[0]),
                Phase.L2: SPCStats(voltage=voltages[1], current=currents[1], power=powers[1]),
                Phase.L3: SPCStats(voltage=voltages[2], current=currents[2], power=powers[2]),
            },
        )
