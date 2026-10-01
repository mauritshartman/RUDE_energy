from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import StrEnum

from common import Logger, ControlStatus, Phase, SPCStats, BaseInverter


class EVChargingStatus(StrEnum):
    INOPERATIVE = 'INOPERATIVE' # EVSE is turned off
    NO_CAR_CONNECTED = 'NO_CAR_CONNECTED' # no EV is currently charging
    CONNECTED_NOT_CHARGING = 'CONNECTED_NOT_CHARGING' # an EV is connected to the charger, but not actively charging (anymore)
    CONNECTED_CHARGING = 'ACTIVELY_CHARGING' # an EV is currently charging
    ERROR = 'ERROR' # some error occurred


@dataclass
class EVChargerStats:
    control_status: ControlStatus = ControlStatus.UNCONTROLLED
    ev_charging_status: EVChargingStatus = EVChargingStatus.NO_CAR_CONNECTED
    total_power_w: Optional[float] = None
    ac_side: dict[Phase, SPCStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'control_status': self.control_status,
            'charging_status': self.ev_charging_status,
            'total_power': self.total_power_w,
            'ac_side': { p: s.to_dict() for p, s in self.ac_side.items() },
        }


class BaseEVCharger(BaseInverter):

    def __init__(self,
        name: str,
        connected_phase: Phase,
        log: Logger,
    ) -> None:
        super().__init__(name, connected_phase, log)

    @abstractmethod
    async def read_stats(self) -> EVChargerStats:
        raise NotImplementedError

    @abstractmethod
    def get_charging_status(self) -> EVChargingStatus:
        '''Return the charging status of this EV charger
        '''
        raise NotImplementedError
