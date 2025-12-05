from enum import Enum
from typing import Any
from dynaconf import Dynaconf


class ControlMode(Enum):
    NONE = 1  # completely idle
    MANUAL = 2  # continuous manual charging / discharging
    STATIC = 3  # automatic charging / discharging according to fixed schedule
    DYNAMIC = 4  # automatic charging / discharging according to a dynamic schedule


class Config:
    _settings = Dynaconf(
        settings_files=['/data/options.json'],
    )

    def __init__(self):
        pass

    def inverter_config(self, name) -> dict:
        for inv_setting in self._settings['inverters']:
            if inv_setting['name'] == name and inv_setting['enable']:
                return inv_setting
        raise Exception(f'cannot find inverter {name} in config')

    def get_inverter_names(self) -> list:
        return [inv['name'] for inv in self._settings['inverters'] if inv['enable']]

    def get_inverter_phase_map(self) -> dict[str, list[str]]:
        '''
        Return a dict that maps the phases (L1, L2, and L3) to enabled inverters (which can be zero or more).
        If no inverter is enabled for a given phase, then its entry in the dict will be an empty list
        '''
        ret = { 'L1': [], 'L2': [], 'L3': [] }
        for inv_setting in self._settings['inverters']:
            if inv_setting['enable']:
                ret[inv_setting['connected_phase']].append(inv_setting['name'])
        return ret

    def get_data_manager_config(self) -> dict:
        return self._settings['data_manager']

    def get_control_mode(self) -> ControlMode:
        cm = str(self._settings['control_mode']).upper()
        return ControlMode[cm]

    def get_debug(self) -> bool:
        return self._settings['debug']

    def get_manual_mode_config(self) -> dict[str, Any]:
        return {
            'charge': self._settings['manual_mode']['charge'],
            'amount': int(self._settings['manual_mode']['amount']),
        }

    def get_loop_delay(self) -> int:
        return int(self._settings['loop_delay'])

config = Config()
