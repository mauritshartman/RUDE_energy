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

    def __init__(self,
        name: str,
        max_fuse_a: int,
        max_phase_current_diff_a: int,
        log: Logger,
    ) -> None:
        self.name = name
        self.max_fuse_a = max_fuse_a
        self.max_phase_current_diff_a = max_phase_current_diff_a
        self.log = log

        # When set, a failure of this energy meter is logged and stepped over instead of reaching the control
        # loop. Note what that means here: the safety checks are built on the grid measurements this meter
        # supplies, so without them no power level can be commanded safely and the control loop stops anyway.
        # Setting this mainly helps across a connection that drops and comes back.
        # Set from the configuration by create_energy_meter, see subsystems/energy_meters/create.py
        self.ignore_errors = False

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def read_stats(self) -> EnergyMeterStats:
        raise NotImplementedError
