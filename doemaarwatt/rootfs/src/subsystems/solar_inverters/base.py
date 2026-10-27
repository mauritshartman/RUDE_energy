from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from enum import StrEnum

from common import Logger, ControlStatus, Phase, SPCStats, BaseInverter


class SolarGenerationStatus(StrEnum):
    UNKNOWN = 'UNKNOWN' # unknown whether solar generation is possible
    GENERATING = 'GENERATING' # solar inverter is generating solar power
    STANDBY = 'STANDBY' # solar inverter is not generating solar power (ie. it is night), but is otherwise functioning nominally


@dataclass
class SolarInverterStats:
    control_status: ControlStatus = ControlStatus.UNCONTROLLED
    solar_status: SolarGenerationStatus = SolarGenerationStatus.UNKNOWN
    setpoint_limit_w: Optional[float] = None
    total_power_w: Optional[float] = None
    ac_side: dict[Phase, SPCStats] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'control_status': self.control_status,
            'solar_status': self.solar_status,
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

    @abstractmethod
    def get_solar_status(self) -> SolarGenerationStatus:
        '''Return the solar status of this solar inverter
        '''
        raise NotImplementedError

    @abstractmethod
    def get_setpoint_limit(self) -> Optional[float]:
        raise NotImplementedError

    @abstractmethod
    async def set_power_limit(self, power_w: Optional[float]) -> None:
        '''Command a maximum output power level to the solar inverter. If None is passed, then the solar inverter
        should remove any existing power (curtailment) limitation, so it can (potentially) output full solar power
        again (if the sun is shining enough). If zero is passed, the solar inverter is instructed to stop solar
        power generation altogether.

        This value is the limit for a single phase. So for a tri-phase system, internally the limit is three times higher.
        The power limit level is the same across all three phases.
        '''
        raise NotImplementedError

    def is_curtailed(self) -> bool:
        '''True iff the solar inverter is being actively curtailed'''
        raise NotImplementedError
