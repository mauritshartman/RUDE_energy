from typing import Any

from common import Logger, ConfigException
from .base import BaseEnergyMeter
from .sma_data_manager import SmaDataManager
from .sim_energy_meter import SimEnergyMeter


ENERGY_METER_MAP = {
    'sma_data_manager': SmaDataManager,
    'sim_energy_meter': SimEnergyMeter,
}

ENERGY_METER_DESCRIPTIONS = {
    'sma_data_manager': 'SMA Data Manager M',
    'sim_energy_meter': 'Simulated energy meter',
}


def create_energy_meter(cfg: dict[str, Any], log: Logger) -> BaseEnergyMeter:
    meter_type = cfg.get('type', 'sma_data_manager')
    if meter_type == 'sma_data_manager':
        subsystem = SmaDataManager.from_config(cfg, log)
    elif meter_type == 'sim_energy_meter':
        subsystem = SimEnergyMeter.from_config(cfg, log)
    else:
        raise ConfigException(f'unknown energy meter type: {meter_type}', source='energy meter instantiation')

    # Errors of a subsystem configured this way are logged and stepped over by the controller rather
    # than stopping the control loop. Set here so no concrete subsystem has to carry it through its
    # own constructor and from_config
    subsystem.ignore_errors = bool(cfg.get('ignore_errors', False))
    return subsystem
