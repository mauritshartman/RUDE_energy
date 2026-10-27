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
        subsystem = SmaSunnyBoyStorage.from_config(cfg, log)
    elif inverter_type == 'sim_battery_inverter':
        subsystem = SimBatteryInverter.from_config(cfg, log)
    else:
        raise ConfigException(f'unknown battery inverter type: {inverter_type}', source='battery inverter instantiation')

    # Errors of a subsystem configured this way are logged and stepped over by the controller rather
    # than stopping the control loop. Set here so no concrete subsystem has to carry it through its
    # own constructor and from_config
    subsystem.ignore_errors = bool(cfg.get('ignore_errors', False))
    return subsystem
