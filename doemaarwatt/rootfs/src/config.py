
import json
from pathlib import Path
from typing import Any

from aiohttp import web

from mode import ControlMode, MIN_MODE_VALUE, MAX_MODE_VALUE
from logger import Logger, LogLevel


# Local development path:
DYN_CONFIG_PATH = Path.home() / Path('dyn_config.json')
# Production build version:
# DYN_CONFIG_PATH = Path('/data/dyn_config.json')

NEKOT = '2d0eecc332c75ab92'  # owned by Bart
NEKOT += 'e5e507ee1664fa1'

NEKOT2 = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJiOGMzMzlkMjI2MjM0MGIwOGNhM2VkZDY1OTVhNDA4My' # created by Bart's home instance
NEKOT2 += 'IsImlhdCI6MTc3NTU1NTk2NCwiZXhwIjoyMDkwOTE1OTY0fQ.HY28ijV94VgjQnRFd_fcpJ086J-5Lhm9OzJeGLVnPRk'


VALID_PHASES = { 'L1', 'L2', 'L3' }
DYN_CONFIG_DEFAULT = {
    'general': {
        'mode': ControlMode['IDLE'],
        'autostart': False,
        'debug': False,
        'loop_delay': 5,
        'timezone_offset': 2,
        'supervisor_token': '',
    },
    'inverters': [],
    'data_manager': {},
    'mode_manual': { 'amount': 0, 'direction': 'standby' },
    'mode_static': { 'schedule': [] },
    'mode_dynamic': {
        'price_update_time': '14:00',
        'update_interval': 3600,
        'resolution': 60,
        'fallback_mode': 1,
        'efficiency': 0.95,
        'api_token': '',
    },
}
GEN_CONFIG = {
    'mode': int,
    'autostart': bool,
    'debug': bool,
    'loop_delay': int,
    'timezone_offset': int,
    'supervisor_token': str,
}
INV_CONFIG = {
    'name': str,
    'enable': bool,
    'host': str,
    'port': int,
    'battery_capacity': int,  # Capacity in Wh of the battery connected to the inverter
    'battery_charge_limit': int,  # Maximum power when charging the battery connected to the inverter
    'battery_discharge_limit': int,  # Maximum power when discharging the battery connected to the inverter
    'connected_phase': str,  # L1 / L2 / L3
}
DM_CONFIG = {
    'host': str,
    'port': int,
    'max_fuse_current': int,
}
VALID_DIRECTION = { 'standby', 'charge', 'discharge' }
MODE_MANUAL_CONFIG = {
    'amount': int,
    'direction': str,  # standby / charge / discharge
}
MODE_STATIC_CONFIG = {
    'schedule': list,  # list of dict {time, direction, amount}
}
STATIC_SCHEDULE_ENTRY = {
    'time': str,
    'amount': int,  # always positive
    'direction': str,
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

        # read dynamic config (stored at /data/dyn_config.json)
        self._dyn_config = DYN_CONFIG_DEFAULT  # dynamic addon configuration
        if DYN_CONFIG_PATH.exists():  # check for save dynamic config from an earlier session
            with DYN_CONFIG_PATH.open() as f:
                self._dyn_config = json.load(f)
                self.log.set_timezone(self.timezone_offset)
                self.log.debug(f'DoeMaarWatt backend server: loaded existing config:\n{self._dyn_config}')
        else:  # no file exists, so create one with default settings
            self.save_dyn_config()
            self.log.set_timezone(self.timezone_offset)
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
            raise ValueError(f'invalid mode value: {m}')
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
    def timezone_offset(self) -> int:
        return int(self._dyn_config['general']['timezone_offset'])
    @timezone_offset.setter
    def timezone_offset(self, tz_offset):
        self.log.info(f'config: setting timezone_offset to {tz_offset}')
        self._dyn_config['general']['timezone_offset'] = int(tz_offset)
        self.save_dyn_config()

    def get_general_config(self) -> dict:
        return self._dyn_config['general']
    def get_inverters_config(self) -> list:
        return self._dyn_config['inverters']
    def get_data_manager_config(self) -> dict:
        return self._dyn_config['data_manager']
    def get_mode_manual_config(self) -> dict[str, Any]:
        return self._dyn_config['mode_manual']
    def get_mode_static_config(self) -> dict[str, Any]:
        return self._dyn_config['mode_static']
    def get_mode_dynamic_config(self) -> dict[str, Any]:
        return self._dyn_config['mode_dynamic']

    def get_inverter_phase_map(self) -> dict[str, str]:
        '''
        Return a dict that maps the enabled inverters (by name) to their connected
        phases.
        '''
        ret = {}
        for inv_setting in self.get_inverters_config():
            if inv_setting['enable']:
                ret[inv_setting['name']] = inv_setting['connected_phase']
        return ret

    def get_phase_inverters_map(self) -> dict[str, list[str]]:
        '''
        Return a dict that maps the phases (L1, L2, and L3) to enabled inverters (which can be zero or more).
        If no inverter is enabled for a given phase, then its entry in the dict will be an empty list
        '''
        ret = { 'L1': [], 'L2': [], 'L3': [] }
        for inv_setting in self.get_inverters_config():
            if inv_setting['enable']:
                ret[inv_setting['connected_phase']].append(inv_setting['name'])
        return ret

    def get_inverter_field_map(self, field: str) -> dict[str, Any]:
        '''Return a dict that maps the enabled inverters (by name) a field from the config'''
        assert field in INV_CONFIG
        ret = {}
        for inv_setting in self.get_inverters_config():
            if inv_setting['enable']:
                ret[inv_setting['name']] = inv_setting[field]
        return ret

    def set_general_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise Exception(f'general config requires a dict, passed: {cfg}')
        if len(set(cfg.keys()) ^ set(GEN_CONFIG.keys())) != 0:
            raise Exception(f'invalid general config (missing or extraneous fields): {cfg}')
        for k, v in cfg.items():
            if not isinstance(v, GEN_CONFIG[k]):
                raise Exception(f'invalid general config: field {k} has invalid value: {v}')
            if k == 'mode' and (v < MIN_MODE_VALUE or v > MAX_MODE_VALUE):
                raise Exception(f'invalid general config: field {k} has invalid value: {v}')

        self.log.info(f'config: setting general config to {cfg}')
        self._dyn_config['general'] = cfg
        self.save_dyn_config()

        self.log.set_loglevel(LogLevel.DEBUG if cfg['debug'] else LogLevel.INFO)

    def set_bart_home_setup(self):
        self.set_data_manager_config({
            'host': '192.168.1.153',
            'port': 502,
            'max_fuse_current': 24,
        })
        self.set_inverters_config([
            {
                'name': 'SBS 6.0-10 L1',
                'enable': True,
                'host': '192.168.1.110',
                'port': 502,
                'battery_capacity': 64000,
                'battery_charge_limit': 6000,
                'battery_discharge_limit': 6000,
                'connected_phase': 'L1',
            },
            {
                'name': 'SBS 6.0-10 L2',
                'enable': True,
                'host': '192.168.1.94',
                'port': 502,
                'battery_capacity': 64000,
                'battery_charge_limit': 6000,
                'battery_discharge_limit': 6000,
                'connected_phase': 'L2',
            },
            {
                'name': 'SBS 5.0-10 L3',
                'enable': True,
                'host': '192.168.1.137',
                'port': 502,
                'battery_capacity': 64000,
                'battery_charge_limit': 5000,
                'battery_discharge_limit': 5000,
                'connected_phase': 'L3',
            },
        ])
        dyn_cfg = self.get_mode_dynamic_config()
        dyn_cfg['api_token'] = NEKOT
        self.set_mode_dynamic_config(dyn_cfg)

        gen_cfg = self.get_general_config()
        gen_cfg['supervisor_token'] = NEKOT2
        self.set_general_config(gen_cfg)

    def set_inverters_config(self, cfg: list):
        if not isinstance(cfg, list):
            raise Exception(f'inverter config requires a list of dicts, passed: {cfg}')

        self._dyn_config['inverters'] = []
        for c in cfg:
            if not isinstance(c, dict):
                raise Exception(f'inverter config requires a list of dicts, passed: {cfg}')
            if len(set(c.keys()) ^ set(INV_CONFIG.keys())) != 0:
                raise Exception(f'invalid inverter config (missing or extraneous fields): {c}')
            for k, v in c.items():
                if not isinstance(v, INV_CONFIG[k]):
                    raise Exception(f'invalid inverter config: field {k} has invalid value: {v}')
                if k == 'connected_phase' and v not in VALID_PHASES:
                    raise Exception(f'invalid inverter config: field {k} has invalid value: {v}')

            self._dyn_config['inverters'].append(c)

        self.log.info(f'config: setting inverters config to:\n{"\n".join(str(s) for s in self._dyn_config["inverters"])}')
        self.save_dyn_config()

    def set_data_manager_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise Exception(f'data manager config requires a dict, passed: {cfg}')
        if len(set(cfg.keys()) ^ set(DM_CONFIG.keys())) != 0:
            raise Exception(f'invalid data manager config (missing or extraneous fields): {cfg}')
        for k, v in cfg.items():
            if not isinstance(v, DM_CONFIG[k]):
                raise Exception(f'invalid data manager config: field {k} has invalid value: {v}')

        self.log.info(f'config: setting data manager config to {cfg}')
        self._dyn_config['data_manager'] = cfg
        self.save_dyn_config()

    def set_mode_manual_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise Exception(f'mode manual config requires a dict, passed: {cfg}')
        if len(set(cfg.keys()) ^ set(MODE_MANUAL_CONFIG.keys())) != 0:
            for k, v in cfg.items():
                if not isinstance(v, MODE_MANUAL_CONFIG[k]):
                    raise Exception(f'invalid mode manual config: field {k} has invalid value: {v}')
                if k == 'direction' and v not in VALID_DIRECTION:
                    raise Exception(f'invalid mode manual config: field {k} has invalid value: {v}')

        self.log.info(f'config: setting manual mode config to {cfg}')
        self._dyn_config['mode_manual'] = cfg
        self.save_dyn_config()

    def set_mode_static_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise Exception(f'mode static config requires a dict, passed: {cfg}')
        for k, v in cfg.items():
            if not isinstance(v, MODE_STATIC_CONFIG[k]):
                raise Exception(f'invalid mode static config: field {k} has invalid value: {v}')
            if k == 'schedule':
                for entry in v:  # must be list of dicts
                    if not isinstance(entry, dict):
                        raise Exception(f'invalid mode static config: schedule should be a list of dicts: {entry}')
                    if len(set(entry.keys()) ^ set(STATIC_SCHEDULE_ENTRY.keys())) != 0:
                        raise Exception(f'invalid mode static config: schedule entry invalid: {entry}')

        self.log.info(f'config: setting static mode config to {cfg}')
        self._dyn_config['mode_static'] = cfg
        self.save_dyn_config()

    def set_mode_dynamic_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            raise Exception(f'mode dynamic config requires a dict, passed: {cfg}')
        self.log.info(f'config: setting dynamic mode config to {cfg}')
        self._dyn_config['mode_dynamic'] = cfg
        self.save_dyn_config()

    # web handlers
    def setup_config_endpoints(self, router):
        router.add_get('/api/config',               self.handle_get_config)
        router.add_get('/api/config/general',       self.handle_get_general_config)
        router.add_post('/api/config/general',      self.handle_post_general_config)
        router.add_get('/api/config/inverters',     self.handle_get_inverter_config)
        router.add_post('/api/config/inverters',    self.handle_post_inverter_config)
        router.add_get('/api/config/data_manager',  self.handle_get_data_manager_config)
        router.add_post('/api/config/data_manager', self.handle_post_data_manager_config)
        router.add_get('/api/config/mode/manual',   self.handle_get_mode_manual_config)
        router.add_post('/api/config/mode/manual',  self.handle_post_mode_manual_config)
        router.add_get('/api/config/mode/static',   self.handle_get_mode_static_config)
        router.add_post('/api/config/mode/static',  self.handle_post_mode_static_config)
        router.add_get('/api/config/mode/dynamic',  self.handle_get_mode_dynamic_config)
        router.add_post('/api/config/mode/dynamic', self.handle_post_mode_dynamic_config)
        router.add_post('/api/config/bart_setup',   self.handle_post_bart_setup)

    async def handle_get_config(self, req: web.Request) -> web.Response:
        return web.json_response(self._dyn_config)

    async def handle_get_general_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_general_config())

    async def handle_get_inverter_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_inverters_config())

    async def handle_get_data_manager_config(self, req: web.Request) -> web.Response:
        return web.json_response(self.get_data_manager_config())

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

    async def handle_post_inverter_config(self, req: web.Request) -> web.Response:
        try:
            parsed = await req.json()
            self.set_inverters_config(parsed)
            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_post_data_manager_config(self, req: web.Request) -> web.Response:
        try:
            parsed = await req.json()
            self.set_data_manager_config(parsed)
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
