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
        return SmaSolarInverter.from_config(cfg, log)
    elif inverter_type == 'sim_solar_inverter':
        return SimSolarInverter.from_config(cfg, log)
    raise ConfigException(f'unknown solar inverter type: {inverter_type}', source='solar inverter instantiation')
