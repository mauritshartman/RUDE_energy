
import json
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web

from mode import ControlMode, MIN_MODE_VALUE, MAX_MODE_VALUE
from common import Logger, LogLevel, Phase, ConfigException
from subsystems.battery_inverters import BATTERY_INVERTER_DESCRIPTIONS
from subsystems.solar_inverters import SOLAR_INVERTER_DESCRIPTIONS
from subsystems.energy_meters import ENERGY_METER_DESCRIPTIONS


# Local development path:
DYN_CONFIG_PATH = Path.home() / Path('dyn_config.json')
# Production build version:
# DYN_CONFIG_PATH = Path('/data/dyn_config.json')

NEKOT = '2d0eecc332c75ab92'  # owned by Bart
NEKOT += 'e5e507ee1664fa1'

NEKOT2 = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJiOGMzMzlkMjI2MjM0MGIwOGNhM2VkZDY1OTVhNDA4My' # created by Bart's home instance
NEKOT2 += 'IsImlhdCI6MTc3NTU1NTk2NCwiZXhwIjoyMDkwOTE1OTY0fQ.HY28ijV94VgjQnRFd_fcpJ086J-5Lhm9OzJeGLVnPRk'


VALID_PHASES = set(Phase)
DYN_CONFIG_DEFAULT = {
    'general': {
        'mode': ControlMode['IDLE'],
        'autostart': False,
        'debug': False,
        'loop_delay': 5,
        'timezone': 'Europe/Amsterdam',
        'supervisor_token': '',
    },
    'battery_inverters': [],
    'solar_inverters': [],
    'energy_meter': {},
    'mode_manual': { 'battery_amount': 0, 'direction': 'standby', 'solar_amount': 0 },
    'mode_static': { 'schedule': [] },
    'mode_dynamic': {
        'price_update_time': '14:00',
        'update_interval': 3600,
        'resolution': 60,
        'fallback_mode': 1,
        'efficiency': 0.93,
        'api_token': '',
    },
}
GEN_CONFIG = {
    'mode': int,
    'autostart': bool,
    'debug': bool,
    'loop_delay': int,
    'timezone': str,
    'supervisor_token': str,
}
# Default per-inverter state-of-charge limits (%), see issue #7. Keep charging below the max and
# discharging above the min so the battery never reaches a full/empty state that puts the inverter to sleep.
DEFAULT_BATTERY_CHARGE_MAX_PCT = 95
DEFAULT_BATTERY_CHARGE_MIN_PCT = 5

BAT_INV_CONFIG = {
    'name': str,
    'type': str,
    'enable': bool,
    'host': str,
    'port': int,
    'battery_capacity': int,  # Capacity in Wh of the battery connected to the inverter
    'battery_charge_limit': int,  # Maximum power when charging the battery connected to the inverter
    'battery_discharge_limit': int,  # Maximum power when discharging the battery connected to the inverter
    'battery_charge_max_pct': int,  # Upper state-of-charge limit (%): do not charge above this
    'battery_charge_min_pct': int,  # Lower state-of-charge limit (%): do not discharge below this
    'connected_phase': Phase,  # L1 / L2 / L3
}
VALID_BATTERY_INVERTER_TYPES = set(BATTERY_INVERTER_DESCRIPTIONS.keys())
EM_CONFIG = {
    'type': str,
    'host': str,
    'port': int,
    'max_fuse_current': int,
}
VALID_ENERGY_METER_TYPES = set(ENERGY_METER_DESCRIPTIONS.keys())
SOL_INV_CONFIG = {
    'name': str,
    'type': str,
    'enable': bool,
    'host': str,
    'port': int,
    'modbus_device_id': int,
    'connected_phase': Phase,
}
VALID_SOLAR_INVERTER_TYPES = set(SOLAR_INVERTER_DESCRIPTIONS.keys())
VALID_DIRECTION = { 'standby', 'charge', 'discharge' }
MODE_MANUAL_CONFIG = {
    'battery_amount': int,
    'direction': str,  # standby / charge / discharge
    'solar_amount': int,
}
MODE_STATIC_CONFIG = {
    'schedule': list,  # list of dict {time, direction, amount}
}
STATIC_SCHEDULE_ENTRY = {
    'time': str,
    'battery_amount': int,  # always positive
    'direction': str,
    'solar_amount': int,
}
MODE_DYNAMIC_CONFIG = {
    'price_update_time': str,
    'update_interval': int,
    'resolution': int,
    'fallback_mode': int,
    'efficiency': float,
    'api_token': str,
}


class DoeMaarWattConfig:
    def __init__(self, logger: Logger):
        self.log = logger
        self.on_general_config_change: Optional[Callable[[], None]] = None  # called when set_general_config() saves

        # read dynamic config (stored at /data/dyn_config.json)
        self._dyn_config = DYN_CONFIG_DEFAULT  # dynamic addon configuration
        if DYN_CONFIG_PATH.exists():  # check for save dynamic config from an earlier session
            with DYN_CONFIG_PATH.open() as f:
                self._dyn_config = json.load(f)
                # migrate old integer timezone_offset to timezone string
                gen = self._dyn_config['general']
                if 'timezone_offset' in gen and 'timezone' not in gen:
                    gen['timezone'] = 'Europe/Amsterdam'
                    del gen['timezone_offset']
                    self.save_dyn_config()
                # backfill per-inverter state-of-charge limits for configs saved before issue #7
                migrated = False
                for inv in self._dyn_config.get('battery_inverters', []):
                    if 'battery_charge_max_pct' not in inv:
                        inv['battery_charge_max_pct'] = DEFAULT_BATTERY_CHARGE_MAX_PCT
                        migrated = True
                    if 'battery_charge_min_pct' not in inv:
                        inv['battery_charge_min_pct'] = DEFAULT_BATTERY_CHARGE_MIN_PCT
                        migrated = True
                if migrated:
                    self.save_dyn_config()
                self.log.set_timezone(self.timezone)
                self.log.debug(f'DoeMaarWatt backend server: loaded existing config:\n{self._dyn_config}')
        else:  # no file exists, so create one with default settings
            self.save_dyn_config()
            self.log.set_timezone(self.timezone)
            self.log.debug(f'DoeMaarWatt backend server: loaded new default config:\n{self._dyn_config}')

        self.log.debug(f'DoeMaarWatt backend server: config stored in {DYN_CONFIG_PATH}')

    def save_dyn_config(self):
        with DYN_CONFIG_PATH.open(mode='w') as f:
            json.dump(self._dyn_config, f)

    @property
    def mode(self):
        return ControlMode(self._dyn_config['general']['mode'])
    @mode.setter
    def mode(self, m: ControlMode | int):
        if isinstance(m, int):
            self.log.info(f'config: setting mode to {m}')
            self._dyn_config['general']['mode'] = m
        elif isinstance(m, ControlMode):
            self.log.info(f'config: setting mode to {m.value}')
            self._dyn_config['general']['mode'] = m.value
        else:
            raise ConfigException(f'invalid mode value: {m}', source='config')
        self.save_dyn_config()

    @property
    def debug(self):
        return self._dyn_config['general']['debug']
    @debug.setter
    def debug(self, dbg):
        self.log.info(f'config: setting debug output to {dbg}')
        self._dyn_config['general']['debug'] = dbg
        self.save_dyn_config()

    @property
    def autostart(self):
        return self._dyn_config['general']['autostart']
    @autostart.setter
    def autostart(self, astart):
        self.log.info(f'config: setting autostart to {astart}')
        self._dyn_config['general']['autostart'] = astart
        self.save_dyn_config()

    @property
    def timezone(self) -> str:
        return str(self._dyn_config['general']['timezone'])
    @timezone.setter
    def timezone(self, tz_name: str):
        self.log.info(f'config: setting timezone to {tz_name}')
        self._dyn_config['general']['timezone'] = str(tz_name)
        self.save_dyn_config()
        self.log.set_timezone(tz_name)

    def get_general_config(self) -> dict:
        return self._dyn_config['general']
    def get_battery_inverters_config(self) -> list:
        return self._dyn_config['battery_inverters']
    def get_solar_inverters_config(self) -> list:
        return self._dyn_config['solar_inverters']
    def get_energy_meter_config(self) -> dict:
        return self._dyn_config['energy_meter']
    def get_mode_manual_config(self) -> dict[str, Any]:
        return self._dyn_config['mode_manual']
    def get_mode_static_config(self) -> dict[str, Any]:
        return self._dyn_config['mode_static']
    def get_mode_dynamic_config(self) -> dict[str, Any]:
        return self._dyn_config['mode_dynamic']

    def get_inverter_phase_map(self) -> dict[str, Phase]:
        '''
        Return a dict that maps the enabled inverters (by name) to their connected
        phases.
        '''
        ret = {}
        for inv_setting in self.get_battery_inverters_config():
            if inv_setting['enable']:
                ret[inv_setting['name']] = inv_setting['connected_phase']
        return ret

    def get_phase_inverters_map(self) -> dict[Phase, list[str]]:
        '''
        Return a dict that maps the phases (L1, L2, and L3) to enabled inverters (which can be zero or more).
        If no inverter is enabled for a given phase, then its entry in the dict will be an empty list
        '''
        ret = { Phase.L1: [], Phase.L2: [], Phase.L3: [] }
        for inv_setting in self.get_battery_inverters_config():
            if inv_setting['enable']:
                connected_phase = inv_setting['connected_phase']
                assert isinstance(connected_phase, Phase)
                if connected_phase == Phase.ALL:
                    ret[Phase.L1].append(inv_setting['name'])
                    ret[Phase.L2].append(inv_setting['name'])
                    ret[Phase.L3].append(inv_setting['name'])
                else:
                    ret[connected_phase].append(inv_setting['name'])

        return ret

    def get_battery_inverter_field_map(self, field: str) -> dict[str, Any]:
        '''Return a dict that maps the enabled inverters (by name) a field from the config'''
        assert field in BAT_INV_CONFIG
        ret = {}
        for inv_setting in self.get_battery_inverters_config():
            if inv_setting['enable']:
                ret[inv_setting['name']] = inv_setting[field]
        return ret

    def set_general_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise ConfigException(f'general config requires a dict, passed: {cfg}', source='config')
        if len(set(cfg.keys()) ^ set(GEN_CONFIG.keys())) != 0:
            raise ConfigException(f'invalid general config (missing or extraneous fields): {cfg}', source='config')
        for k, v in cfg.items():
            if not isinstance(v, GEN_CONFIG[k]):
                raise ConfigException(f'invalid general config: field {k} has invalid value: {v}', source='config')
            if k == 'mode' and (v < MIN_MODE_VALUE or v > MAX_MODE_VALUE):
                raise ConfigException(f'invalid general config: field {k} has invalid value: {v}', source='config')
            if k == 'timezone':
                try:
                    ZoneInfo(v)
                except ZoneInfoNotFoundError:
                    raise ConfigException(f'invalid general config: field {k} has invalid value: {v}', source='config')

        self.log.info(f'config: setting general config to {cfg}')
        self._dyn_config['general'] = cfg
        self.save_dyn_config()

        self.log.set_loglevel(LogLevel.DEBUG if cfg['debug'] else LogLevel.INFO)
        self.log.set_timezone(cfg['timezone'])
        if self.on_general_config_change is not None:
            self.on_general_config_change()

    def set_bart_home_setup(self):
        self.set_energy_meter_config({
            'type': 'sma_data_manager',
            'host': '192.168.1.153',
            'port': 502,
            'max_fuse_current': 24,
        })
        self.set_battery_inverters_config([
            {
                'name': 'SBS 6.0-10 L1',
                'type': 'sma_sunny_boy_storage',
                'enable': True,
                'host': '192.168.1.110',
                'port': 502,
                'battery_capacity': 64000,
                'battery_charge_limit': 6000,
                'battery_discharge_limit': 6000,
                'battery_charge_max_pct': DEFAULT_BATTERY_CHARGE_MAX_PCT,
                'battery_charge_min_pct': DEFAULT_BATTERY_CHARGE_MIN_PCT,
                'connected_phase': Phase.L1,
            },
            {
                'name': 'SBS 6.0-10 L2',
                'type': 'sma_sunny_boy_storage',
                'enable': True,
                'host': '192.168.1.94',
                'port': 502,
                'battery_capacity': 64000,
                'battery_charge_limit': 6000,
                'battery_discharge_limit': 6000,
                'battery_charge_max_pct': DEFAULT_BATTERY_CHARGE_MAX_PCT,
                'battery_charge_min_pct': DEFAULT_BATTERY_CHARGE_MIN_PCT,
                'connected_phase': Phase.L2,
            },
            {
                'name': 'SBS 5.0-10 L3',
                'type': 'sma_sunny_boy_storage',
                'enable': True,
                'host': '192.168.1.137',
                'port': 502,
                'battery_capacity': 64000,
                'battery_charge_limit': 5000,
                'battery_discharge_limit': 5000,
                'battery_charge_max_pct': DEFAULT_BATTERY_CHARGE_MAX_PCT,
                'battery_charge_min_pct': DEFAULT_BATTERY_CHARGE_MIN_PCT,
                'connected_phase': Phase.L3,
            },
        ])
        self.set_solar_inverters_config([{
            'name': 'SMA Sunny Tripower',
            'enable': True,
            'type': 'sma_stp_x25',
            'host': '192.168.1.223',
            'port': 502,
            'modbus_device_id': 3,
            'connected_phase': Phase.ALL,
        }])
        dyn_cfg = self.get_mode_dynamic_config()
        dyn_cfg['api_token'] = NEKOT
        self.set_mode_dynamic_config(dyn_cfg)

        gen_cfg = self.get_general_config()
        gen_cfg['supervisor_token'] = NEKOT2
        self.set_general_config(gen_cfg)

    def set_battery_inverters_config(self, cfg: list):
        if not isinstance(cfg, list):
            raise ConfigException(f'battery inverters config requires a list of dicts, passed: {cfg}', source='config')

        taken_names = { i['name'] for i in self._dyn_config['solar_inverters'] }

        self._dyn_config['battery_inverters'] = []
        for c in cfg: # check each battery inverter config
            if not isinstance(c, dict):
                raise ConfigException(f'battery inverters config requires a list of dicts, passed: {cfg}', source='config')
            if len(set(c.keys()) ^ set(BAT_INV_CONFIG.keys())) != 0:
                raise ConfigException(f'invalid battery inverter config (missing or extraneous fields): {c}', source='config')

            # ensure connected_phase is converted before checking types of all fields
            try:
                c['connected_phase'] = Phase(c['connected_phase'])
            except ValueError as e:
                raise ConfigException(f'invalid battery inverter config: connected_phase has invalid value: {e}', source='config')

            for k, v in c.items():
                if not isinstance(v, BAT_INV_CONFIG[k]):
                    raise ConfigException(f'invalid battery inverter config: field {k} has invalid value: {v}', source='config')
                if k == 'type' and v not in VALID_BATTERY_INVERTER_TYPES:
                    raise ConfigException(f'invalid battery inverter type: field {k} has invalid value: {v}', source='config')
                if k == 'name' and v in taken_names:
                    raise ConfigException(f'invalid battery inverter name: there is another inverter named {v}', source='config')

            if not (0 <= c['battery_charge_min_pct'] < c['battery_charge_max_pct'] <= 100):
                raise ConfigException(
                    f'invalid battery inverter config: state-of-charge limits must satisfy '
                    f'0 <= min ({c["battery_charge_min_pct"]}) < max ({c["battery_charge_max_pct"]}) <= 100',
                    source='config')

            taken_names.add(c['name'])  # reserve so no later battery/solar inverter can reuse it
            self._dyn_config['battery_inverters'].append(c)

        self.log.info(f'config: setting battery inverters config to:\n{"\n".join(str(s) for s in self._dyn_config["battery_inverters"])}')
        self.save_dyn_config()

    def set_solar_inverters_config(self, cfg: list):
        if not isinstance(cfg, list):
            raise ConfigException(f'solar inverter config requires a list of dicts, passed: {cfg}', source='config')

        taken_names = { i['name'] for i in self._dyn_config['battery_inverters'] }

        self._dyn_config['solar_inverters'] = []
        for c in cfg:
            if not isinstance(c, dict):
                raise ConfigException(f'solar inverters config requires a list of dicts, passed: {cfg}', source='config')

            if len(set(c.keys()) ^ set(SOL_INV_CONFIG.keys())) != 0:
                raise ConfigException(f'invalid solar inverter config (missing or extraneous fields): {c}', source='config')

            # ensure connected_phase is converted before checking types of all fields
            try:
                c['connected_phase'] = Phase(c['connected_phase'])
            except ValueError as e:
                raise ConfigException(f'invalid solar inverter config: connected_phase has invalid value: {e}', source='config')

            for k, v in c.items():
                if not isinstance(v, SOL_INV_CONFIG[k]):
                    raise ConfigException(f'invalid solar inverter config: field {k} has invalid value: {v}', source='config')
                if k == 'type' and v not in VALID_SOLAR_INVERTER_TYPES:
                    raise ConfigException(f'invalid solar inverter type: field {k} has invalid value: {v}', source='config')
                if k == 'name' and v in taken_names:
                    raise ConfigException(f'invalid solar inverter name: there is another inverter named {v}', source='config')

            taken_names.add(c['name']) # reserve so no later solar/battery inverter can reuse it
            self._dyn_config['solar_inverters'].append(c)

        self.log.info(f'config: setting solar inverters config to:\n{"\n".join(str(s) for s in self._dyn_config["solar_inverters"])}')
        self.save_dyn_config()

    def set_energy_meter_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise ConfigException(f'energy meter config requires a dict, passed: {cfg}', source='config')
        if len(set(cfg.keys()) ^ set(EM_CONFIG.keys())) != 0:
            raise ConfigException(f'invalid energy meter config (missing or extraneous fields): {cfg}', source='config')
        for k, v in cfg.items():
            if not isinstance(v, EM_CONFIG[k]):
                raise ConfigException(f'invalid energy meter config: field {k} has invalid value: {v}', source='config')
            if k == 'type' and v not in VALID_ENERGY_METER_TYPES:
                raise ConfigException(f'invalid energy meter type: field {k} has invalid value: {v}', source='config')

        self.log.info(f'config: setting energy meter config to {cfg}')
        self._dyn_config['energy_meter'] = cfg
        self.save_dyn_config()

    def set_mode_manual_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise ConfigException(f'mode manual config requires a dict, passed: {cfg}', source='config')
        if len(set(cfg.keys()) ^ set(MODE_MANUAL_CONFIG.keys())) != 0:
            for k, v in cfg.items():
                if not isinstance(v, MODE_MANUAL_CONFIG[k]):
                    raise ConfigException(f'invalid mode manual config: field {k} has invalid value: {v}', source='config')
                if k == 'direction' and v not in VALID_DIRECTION:
                    raise ConfigException(f'invalid mode manual config: field {k} has invalid value: {v}', source='config')

        self.log.info(f'config: setting manual mode config to {cfg}')
        self._dyn_config['mode_manual'] = cfg
        self.save_dyn_config()

    def set_mode_static_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise ConfigException(f'mode static config requires a dict, passed: {cfg}', source='config')
        for k, v in cfg.items():
            if not isinstance(v, MODE_STATIC_CONFIG[k]):
                raise ConfigException(f'invalid mode static config: field {k} has invalid value: {v}', source='config')
            if k == 'schedule':
                for entry in v:  # must be list of dicts
                    if not isinstance(entry, dict):
                        raise ConfigException(f'invalid mode static config: schedule should be a list of dicts: {entry}', source='config')
                    if len(set(entry.keys()) ^ set(STATIC_SCHEDULE_ENTRY.keys())) != 0:
                        raise ConfigException(f'invalid mode static config: schedule entry invalid: {entry}', source='config')

        self.log.info(f'config: setting static mode config to {cfg}')
        self._dyn_config['mode_static'] = cfg
        self.save_dyn_config()

    def set_mode_dynamic_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise ConfigException(f'mode dynamic config requires a dict, passed: {cfg}', source='config')
        self.log.info(f'config: setting dynamic mode config to {cfg}')
        self._dyn_config['mode_dynamic'] = cfg
        self.save_dyn_config()

    # web handlers
    def setup_config_endpoints(self, router):
        router.add_get('/api/config',                       self.handle_get_config)
        router.add_get('/api/config/general',               self.handle_get_general_config)
        router.add_post('/api/config/general',              self.handle_post_general_config)
        router.add_get('/api/config/battery_inverters',     self.handle_get_battery_inverters_config)
        router.add_post('/api/config/battery_inverters',    self.handle_post_battery_inverters_config)
        router.add_get('/api/config/solar_inverters',       self.handle_get_solar_inverters_config)
        router.add_post('/api/config/solar_inverters',      self.handle_post_solar_inverters_config)
        router.add_get('/api/config/energy_meter',          self.handle_get_energy_meter_config)
        router.add_post('/api/config/energy_meter',         self.handle_post_energy_meter_config)
        router.add_get('/api/config/mode/manual',           self.handle_get_mode_manual_config)
        router.add_post('/api/config/mode/manual',          self.handle_post_mode_manual_config)
        router.add_get('/api/config/mode/static',           self.handle_get_mode_static_config)
        router.add_post('/api/config/mode/static',          self.handle_post_mode_static_config)
        router.add_get('/api/config/mode/dynamic',          self.handle_get_mode_dynamic_config)
        router.add_post('/api/config/mode/dynamic',         self.handle_post_mode_dynamic_config)
        router.add_post('/api/config/bart_setup',           self.handle_post_bart_setup)
        router.add_get('/api/config/subsystem_types',       self.handle_subsystem_types)

    async def handle_get_config(self, req: web.Request) -> web.Response:
        return web.json_response(self._dyn_config)

    async def handle_get_general_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_general_config())

    async def handle_get_battery_inverters_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_battery_inverters_config())

    async def handle_get_solar_inverters_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_solar_inverters_config())

    async def handle_get_energy_meter_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_energy_meter_config())

    async def handle_get_mode_manual_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_mode_manual_config())

    async def handle_get_mode_static_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_mode_static_config())

    async def handle_get_mode_dynamic_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_mode_dynamic_config())

    async def handle_post_general_config(self, req: web.Request) -> web.Response:
        try:
            parsed = await req.json()
            self.set_general_config(parsed)
            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_post_battery_inverters_config(self, req: web.Request) -> web.Response:
        try:
            parsed = await req.json()
            self.set_battery_inverters_config(parsed)
            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_post_solar_inverters_config(self, req: web.Request) -> web.Response:
        try:
            parsed = await req.json()
            self.set_solar_inverters_config(parsed)
            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_post_energy_meter_config(self, req: web.Request) -> web.Response:
        try:
            parsed = await req.json()
            self.set_energy_meter_config(parsed)
            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_post_mode_manual_config(self, req: web.Request) -> web.Response:
        try:
            parsed = await req.json()
            self.set_mode_manual_config(parsed)
            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_post_mode_static_config(self, req: web.Request) -> web.Response:
        try:
            parsed = await req.json()
            self.set_mode_static_config(parsed)
            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_post_mode_dynamic_config(self, req: web.Request) -> web.Response:
        try:
            parsed = await req.json()
            self.set_mode_dynamic_config(parsed)
            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_post_bart_setup(self, req: web.Request) -> web.Response:
        try:
            self.set_bart_home_setup()
            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_subsystem_types(self, req: web.Request) -> web.Response:
        return web.json_response({
            'battery_inverters': BATTERY_INVERTER_DESCRIPTIONS,
            'solar_inverters': SOLAR_INVERTER_DESCRIPTIONS,
            'energy_meters': ENERGY_METER_DESCRIPTIONS,
        })
