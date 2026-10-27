from typing import Any

from common import Logger, ConfigException
from .base import BaseSolarInverter
from .sma_solar_inverter import SmaSolarInverter
from .sim_solar_inverter import SimSolarInverter


SOLAR_INVERTER_MAP = {
    'sma_stp_x25': SmaSolarInverter,
    'sim_solar_inverter': SimSolarInverter,
}

SOLAR_INVERTER_DESCRIPTIONS = {
    'sma_stp_x25': 'SMA STP X-25',
    'sim_solar_inverter': 'Simulated 30kW Solar Inverter',
}


def create_solar_inverter(cfg: dict[str, Any], log: Logger) -> BaseSolarInverter:
    inverter_type = cfg.get('type', 'sma')
    if inverter_type == 'sma_stp_x25':
        subsystem = SmaSolarInverter.from_config(cfg, log)
    elif inverter_type == 'sim_solar_inverter':
        subsystem = SimSolarInverter.from_config(cfg, log)
    else:
        raise ConfigException(f'unknown solar inverter type: {inverter_type}', source='solar inverter instantiation')

    # Errors of a subsystem configured this way are logged and stepped over by the controller rather
    # than stopping the control loop. Set here so no concrete subsystem has to carry it through its
    # own constructor and from_config
    subsystem.ignore_errors = bool(cfg.get('ignore_errors', False))
    return subsystem
