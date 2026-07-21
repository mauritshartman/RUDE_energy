from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any

from common import Logger, ControlStatus, Phase, SPCStats


def _phase_status(power: Optional[float]) -> str:
    if power is None or power == 0:
        return 'no flow / disconnected'
    return 'drawing from grid' if power < 0 else 'supplying to grid'


@dataclass
class EnergyMeterStats:
    control_status: ControlStatus
    max_fuse_a: int

    grid: dict[Phase, SPCStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        assert not Phase.ALL in self.grid
        assert Phase.L1 in self.grid
        assert Phase.L2 in self.grid
        assert Phase.L3 in self.grid

        ret: dict[str, Any] = { 'control_status': self.control_status }
        for phi, s in self.grid.items():
            ret[str(phi)] = {
                'Amax': self.max_fuse_a,
                'A': s.current,
                'V': s.voltage,
                'P': s.power,
                'status': _phase_status(s.power),
            }

        return ret


class BaseEnergyMeter(ABC):

    def __init__(self, name: str, max_fuse_a: int, log: Logger) -> None:
        self.name = name
        self.max_fuse_a = max_fuse_a
        self.log = log

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def read_stats(self) -> EnergyMeterStats:
        raise NotImplementedError
