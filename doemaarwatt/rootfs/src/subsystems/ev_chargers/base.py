from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import StrEnum

from common import Logger, ControlStatus, Phase, SPCStats, BaseInverter, ConfigException


EV_CHARGER_STRAIGHT_MAPPING = 'gridL1:evseL1,gridL2:evseL2,gridL3:evseL3'

VALID_EV_CHARGER_PHASE_MAPPINGS = {
    EV_CHARGER_STRAIGHT_MAPPING, # straight mapping
    'gridL1:evseL2,gridL2:evseL1,gridL3:evseL3', # L1 & L2 swapped
    'gridL1:evseL1,gridL2:evseL3,gridL3:evseL2', # L2 & L3 swapped
    'gridL1:evseL3,gridL2:evseL2,gridL3:evseL1', # L1 & L3 swapped
    'gridL1:evseL2,gridL2:evseL3,gridL3:evseL1', # rotate 1 right
    'gridL1:evseL3,gridL2:evseL1,gridL3:evseL2', # rotate 2 right
}



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
        phase_map_str: str,
    ) -> None:
        super().__init__(name, connected_phase, log)

        if phase_map_str not in VALID_EV_CHARGER_PHASE_MAPPINGS:
            raise ConfigException(f'invalid phase mapping passed: {phase_map_str}', source='BaseEVCharger')
        self._phase_map: dict[Phase, Phase] = {} # grid -> evse
        for pair in phase_map_str.split(','):
            g, e = pair.split(':', maxsplit=1)
            self._phase_map[Phase(g[-2:])] = Phase(e[-2:])
        self._inv_phase_map: dict[Phase, Phase] = {v: k for k, v in self._phase_map.items()} # evse -> grid

    def grid_to_evse_phase(self, grid_phase: Phase) -> Phase:
        return self._phase_map[grid_phase]

    def evse_to_grid_phase(self, evse_phase: Phase) -> Phase:
        return self._inv_phase_map[evse_phase]

    @abstractmethod
    async def read_stats(self) -> EVChargerStats:
        raise NotImplementedError

    @abstractmethod
    def get_charging_status(self) -> EVChargingStatus:
        '''Return the charging status of this EV charger
        '''
        raise NotImplementedError
