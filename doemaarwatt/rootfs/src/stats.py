from typing import Optional, Any
from dataclasses import dataclass

from common import Phase, PhasePowerMap
from config import DoeMaarWattConfig
from subsystems.battery_inverters import BatteryInverterStats
from subsystems.solar_inverters import SolarInverterStats
from subsystems.energy_meters import EnergyMeterStats


class ControllerStats:
    def __init__(self,
        cfg: DoeMaarWattConfig,
    ) -> None:

        self.battery_inverters: dict[str, BatteryInverterStats] = {}
        self.solar_inverters: dict[str, SolarInverterStats] = {}
        self.energy_meter: Optional[EnergyMeterStats] = None

        self.start_ts: Optional[float] = None

    def reset(self):
        self.battery_inverters = {}
        self.solar_inverters = {}
        self.energy_meter = None

        self.start_ts = None

    def get_PBSnow(self, phi: Phase) -> PhasePowerMap:
        '''Based on the latest battery and solar inverter power measurements, create a PBSnow power mapping
        for each inverter
        '''
        ret = PhasePowerMap(phase=phi)

        # grab current power level from each battery inverter connected to this phase:
        for inv_name, inv_stats in self.battery_inverters.items():
            if phi in inv_stats.ac_side:
                inv_power = inv_stats.ac_side[phi].power
                if not inv_power is None:
                    ret.inv_power[inv_name] = inv_power

        # grab current power level from each solar inverter connected to this phase:
        for inv_name, inv_stats in self.solar_inverters.items():
            if phi in inv_stats.ac_side:
                inv_power = inv_stats.ac_side[phi].power
                if not inv_power is None:
                    ret.inv_power[inv_name] = inv_power

        return ret

    def serialize(self) -> dict[str, Any]:
        return {
            'battery_inverters': { n: s.to_dict() for n, s in self.battery_inverters.items() },
            'solar_inverters': { n: s.to_dict() for n, s in self.solar_inverters.items() },
            'energy_meter': None if self.energy_meter is None else self.energy_meter.to_dict(),
        }
