from typing import Any

from common import Logger, ConfigException
from .base import BaseBatteryInverter
from .sma_sunny_boy_storage import SmaSunnyBoyStorage
from .sim_battery_inverter import SimBatteryInverter


BATTERY_INVERTER_MAP = {
    'sma_sunny_boy_storage': SmaSunnyBoyStorage,
    'sim_battery_inverter': SimBatteryInverter,
}

BATTERY_INVERTER_DESCRIPTIONS = {
    'sma_sunny_boy_storage': 'SMA Sunny Boy Storage',
    'sim_battery_inverter': 'Simulated battery inverter',
}


def create_battery_inverter(cfg: dict[str, Any], log: Logger) -> BaseBatteryInverter:
    inverter_type = cfg.get('type', 'sim_battery_inverter')
    if inverter_type == 'sma_sunny_boy_storage':
        return SmaSunnyBoyStorage.from_config(cfg, log)
    elif inverter_type == 'sim_battery_inverter':
        return SimBatteryInverter.from_config(cfg, log)
    raise ConfigException(f'unknown battery inverter type: {inverter_type}', source='battery inverter instantiation')
