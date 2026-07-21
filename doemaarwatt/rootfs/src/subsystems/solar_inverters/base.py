from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from common import Logger, ControlStatus, Phase, SPCStats, BaseInverter


@dataclass
class SolarInverterStats:
    control_status: ControlStatus = ControlStatus.UNCONTROLLED
    setpoint_limit_w: Optional[float] = None
    total_power_w: Optional[float] = None
    ac_side: dict[Phase, SPCStats] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'control_status': self.control_status,
            'setpoint_limit': self.setpoint_limit_w,
            'total_power': self.total_power_w,
            'ac_side': { p: s.to_dict() for p, s in self.ac_side.items() },
        }


class BaseSolarInverter(BaseInverter):

    def __init__(self, name: str, connected_phase: Phase, log: Logger) -> None:
        super().__init__(name, connected_phase, log)

    @abstractmethod
    async def read_stats(self) -> SolarInverterStats:
        '''Read various key metrics from the solar inverter over the established (modbus) connection.
        A connection needs to be present as a precondition.
        '''
        raise NotImplementedError
