from enum import Enum
from dynaconf import Dynaconf


class ControlMode(Enum):
    NONE = 1  # completely idle
    CHARGE = 2  # continuous manual charging
    DISCHARGE = 3  # continuous manual discharging
    STATIC_SCHEDULE = 4  # automatic charging / discharging according to fixed schedule
    DYNAMIC_SCHEDULE = 5  # automatic charging / discharging according to a dynamic schedule


class Config:
    _settings = Dynaconf(
        settings_files=['/data/options.json'],
    )

    def __init__(self):
        pass

    def inverter_config(self, name) -> dict:
        for inv_setting in self._settings['inverters']:
            if inv_setting['name'] == name:
                return inv_setting
        raise Exception(f'cannot find inverter {name} in config')

    def get_inverter_names(self) -> list:
        return [inv['name'] for inv in self._settings['inverters']]

    def get_control_mode(self) -> ControlMode:
        cm = str(self._settings['control_mode']).upper()
        return ControlMode[cm]

    def get_charge_amount(self) -> int:
        return int(self._settings['mode_2']['total_charge_amount'])

    def get_discharge_amount(self) -> int:
        return int(self._settings['mode_3']['total_discharge_amount'])

config = Config()
