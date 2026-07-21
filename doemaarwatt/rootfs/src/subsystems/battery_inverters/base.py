from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import StrEnum

from common import Logger, ControlStatus, Phase, SPCStats, BaseInverter


class BatteryStatus(StrEnum):
    DISCONNECTED = 'disconnected'
    STANDBY = 'standby'
    CHARGING = 'charging'
    DISCHARGING = 'discharging'


@dataclass
class BatteryStats:
    '''BatteryStats contains key battery metrics'''
    battery_status: BatteryStatus = BatteryStatus.DISCONNECTED
    battery_current: Optional[float] = None
    battery_voltage: Optional[float] = None
    battery_charge_pct: Optional[float] = None
    battery_temp_low_c: Optional[float] = None
    battery_temp_high_c: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'A': self.battery_current,
            'V': self.battery_voltage,
            'status': self.battery_status,
            'charge': self.battery_charge_pct,
            'temp_l': self.battery_temp_low_c,
            'temp_h': self.battery_temp_high_c,
        }


@dataclass
class BatteryInverterStats:
    control_status: ControlStatus = ControlStatus.UNCONTROLLED
    battery: BatteryStats = field(default_factory=BatteryStats)
    ac_side: dict[Phase, SPCStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'control_status': self.control_status,
            'battery': self.battery.to_dict(),
            'ac_side': { p: s.to_dict() for p, s in self.ac_side.items() },
        }


class BaseBatteryInverter(BaseInverter):

    def __init__(self,
        name: str,
        connected_phase: Phase,
        capacity_wh: int,
        charge_limit_w: int,
        discharge_limit_w: int,
        log: Logger,
    ) -> None:
        super().__init__(name, connected_phase, log)

        assert capacity_wh > 0, f'capacity for {name} must be a positive amount of Wh'
        self.capacity_wh = capacity_wh

        self.charge_limit_w = -1 * abs(charge_limit_w) # ensure charging limit is zero or negative
        self.discharge_limit_w = abs(discharge_limit_w) # ensure discharging limit is zero or positive

    @abstractmethod
    async def read_stats(self) -> BatteryInverterStats:
        '''Read various key metrics from the battery inverter over the established (modbus) connection.
        A connection needs to be present as a precondition.
        '''
        raise NotImplementedError

    @abstractmethod
    async def read_charge_wh(self) -> Optional[float]:
        raise NotImplementedError

    @property
    def power_limits_phase(self) -> tuple[float, float]:
        '''Lower (charge power) and upper (discharge power) limits for the battery inverter, expressed in Watts.
        Commanded power must be within this range. Applies separately to each phase the inverter is connected to.
        '''
        ret = (
            self.charge_limit_w, # charge power has a negative value
            self.discharge_limit_w, # discharge power has a positive value
        )
        assert ret[0] <= ret[1]

        return ret
