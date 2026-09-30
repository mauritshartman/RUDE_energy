from typing import Any

from common import Logger, ConfigException
from .base import BaseEVCharger
from .alfen_eve_pro import AlfenEvePro


EV_CHARGER_MAP = {
    'alfen_eve_pro': AlfenEvePro,
}

EV_CHARGER_DESCRIPTIONS = {
    'alfen_eve_pro': 'Alfen Eve Single Pro',
}


def create_ev_charger(cfg: dict[str, Any], log: Logger) -> BaseEVCharger:
    ev_charger_type = cfg.get('type', 'alfen_eve_pro')
    if ev_charger_type == 'alfen_eve_pro':
        return AlfenEvePro.from_config(cfg, log)
    raise ConfigException(f'unknown EV charger type: {ev_charger_type}', source='EV charger instantiation')
