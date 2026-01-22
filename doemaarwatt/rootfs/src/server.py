import asyncio
import signal
import tempfile
import os
from datetime import datetime as dt
from pathlib import Path
import time
import json
from aiohttp import web
from typing import Callable, Awaitable
import aiohttp_cors

from modbus import ModbusManager, to_s32_list
from config import DoeMaarWattConfig, ControlMode
from stats import DM, battery_stats, data_manager_stats
from pbsent import calc_PBsent
from logger import Logger, LogLevel


API_SERVER_PORT = 8099  # Home Assistant ingress port
FRONTEND_PATH = (Path(__file__).parent / 'web/dist').resolve()
# FRONTEND_PATH = Path('/src/web/dist')
CONTENT_TYPE_MAP = {
    '.html': 'text/html',
    '.css': 'text/css',
    '.js': 'text/javascript',
}

LOG_PATH = Path('/data/logs/')
LOG_PATH = Path('logs/')

def get_ingress_filters(ingress_path: str) -> list:
    return [
        ( 'href="/', f'href="{ingress_path}/' ),
        ( 'src="/src/', f'src="{ingress_path}/src/' ),
        ( 'src="/assets/', f'src="{ingress_path}/assets/' ),
        ( 'fetch("/api"+', f'fetch("{ingress_path}/api"+' ),
        ( 'fetch("/api/log"', f'fetch("{ingress_path}/api/log"' ),
        ( '<script src="/', f'<script src="{ingress_path}/' ),
        ( "top.location.href='", f"top.location.href='{ingress_path}" ),
    ]


class DoeMaarWattServer:
    def __init__(self) -> None:
        # control related variables
        self.log = Logger(loglevel=LogLevel.DEBUG, filedir=LOG_PATH, rotate=10)
        self.config = DoeMaarWattConfig(logger=self.log)
        self.log.set_loglevel(LogLevel.DEBUG if self.config.debug else LogLevel.INFO)
        self.mode = self.config.mode  # use configured startup mode

        # webserver related:
        self.app = web.Application(middlewares=[self.filter_ingress_prefix])
        self.setup_app()
        self.main_task: asyncio.Task = None
        self.sub_task: asyncio.Task = None
        self.running = True  # for main control loop
        self.sub_running = self.config.autostart  # for sub control loop
        self.sub_running_start = None
        self.reset_stats()

        def sig_handler(sig, frame):
            self.log.info(f'\nSIGINT received')
            self.stop()
        signal.signal(signal.SIGINT, sig_handler)

    def setup_app(self) -> None:
        # super static routing with filtering:
        try:
            directory = Path(FRONTEND_PATH)#.expanduser().resolve(strict=True)
        except FileNotFoundError as error:
            raise ValueError(f"'{directory}' does not exist") from error
        if not directory.is_dir():
            raise ValueError(f"'{directory}' is not a directory")
        self._static_dir = directory
        # self.app.router.register_resource(FilteredStaticResource('/', self._static_dir))
        self.app.router.add_static('/', self._static_dir, show_index=True)

        self.app.router.add_get('/api/', self.handle_root)
        self.app.router.add_post('/api/run', self.handle_run)
        self.app.router.add_post('/api/log', self.log.handle_log)
        self.config.setup_config_endpoints(self.app.router)

        cors = aiohttp_cors.setup(self.app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*"
            )
        })
        for route in list(self.app.router.routes()):
            cors.add(route)

    async def run(self) -> None:
        self.main_task = asyncio.create_task(self.control_loop())
        await asyncio.sleep(1)
        await self.main_task

    def stop(self) -> None:
        self.running = False
        if not self.main_task is None:
            self.main_task.cancel()
            self.main_task = None

    def stop_sub_task(self) -> None:
        self.sub_running = False
        self.sub_running_start = None
        if not self.sub_task is None:
            self.sub_task.cancel()
            self.sub_task = None

    async def control_loop(self) -> None:
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host=None, port=API_SERVER_PORT)  # None for all interfaces (see https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.TCPSite)
        await site.start()
        self.log.info(f'backend webserver started on {API_SERVER_PORT}')

        while self.running:  # will only be stopped by a stop() / SIGINT
            try:
                self.log.debug(f'waiting for running to become true')
                while not self.sub_running:  # busy waiting until sub_task can start running
                    await asyncio.sleep(0.25)

                self.mode = self.config.mode  # use configured startup mode
                self.log.info(f'we are running: determined startup mode {self.mode}')
                if self.mode == ControlMode.IDLE:
                    self.sub_task = asyncio.create_task(self.mode_1_loop())
                elif self.mode == ControlMode.MANUAL:
                    self.sub_task = asyncio.create_task(self.mode_2_loop())

                self.sub_running_start = time.time()
                await self.sub_task

            except asyncio.CancelledError:
                self.log.debug('main control loop handling cancel')
                self.stop_sub_task()

        await runner.cleanup()
        self.log.info(f'backend webserver stopped')

    def reset_stats(self):
        self.stats = {
            'inverters': None,
            'data_manager': None,
            'inv_control': None,
        }

    async def mode_1_loop(self):
        self.log.info(f'mode 1 loop started')

        # check if startup conditions are met:
        inv_cfg = self.config.get_inverters_config()
        dm_cfg = self.config.get_data_manager_config()
        if len(dm_cfg) > 0:
            dm_cfg['name'] = DM

        while self.sub_running:
            try:
                inverters = ModbusManager(client_configs=inv_cfg, debug=self.config.debug)
                dm = ModbusManager(client_configs=[dm_cfg], debug=self.config.debug)
                await inverters.connect()
                await dm.connect()

                self.log.info(f'idle: relinquish control and reset power set point')
                await inverters.write_registers_parallel(40149, [0, 0])  # reset rendement
                await inverters.write_registers_parallel(40151, [0, 803])  # 803 = inactive

                self.stats['inverters'] = await battery_stats(inverters, self.config.get_inverter_phase_map())
                self.stats['data_manager'] = await data_manager_stats(dm, dm_cfg.get('max_fuse_current', 25))

                await asyncio.sleep(self.config.get_general_config().get('loop_delay', 10))
            except asyncio.CancelledError:
                self.log.info(f'mode 1 loop cancelled')
                raise
            finally:
                inverters.close()
                dm.close()
                self.reset_stats()
                self.log.info(f'closed modbus connections')

    async def mode_2_loop(self):
        self.log.info(f'Mode 2 (manual mode) started')

        manual_cfg = self.config.get_mode_manual_config()
        charge_amount = manual_cfg.get('amount', 0)
        if manual_cfg['direction'] in ['idle', 'standby']:
            charge_amount = 0  # ensure amount is set to zero in standby mode
        inv_phase_map = self.config.get_phase_inverters_map()
        PBapp_phases = { phase: (charge_amount if len(inv_names) > 0 else 0) for phase, inv_names in inv_phase_map.items() }

        inv_cfg = self.config.get_inverters_config()
        dm_cfg = self.config.get_data_manager_config()
        if len(dm_cfg) > 0:
            dm_cfg['name'] = DM

        while self.sub_running:
            try:
                inverters = ModbusManager(client_configs=inv_cfg, debug=self.config.debug)
                dm = ModbusManager(client_configs=[dm_cfg], debug=self.config.debug)
                await inverters.connect()
                await dm.connect()

                await inverters.write_registers_parallel(40151, [0, 802])  # 802 = active

                # get necessary stats
                self.stats['inverters'] = await battery_stats(inverters, self.config.get_inverter_phase_map())
                self.stats['data_manager'] = await data_manager_stats(dm, dm_cfg.get('max_fuse_current', 25))

                # determine PBsent for each phase
                self.log.info(f'manual mode: computing safe charge/discharge amount (PBsent) for each phase:')
                PBsent_phases = {}

                self.stats['inv_control'] = {}
                for phi in ['L1', 'L2', 'L3']:
                    PBapp = PBapp_phases[phi]
                    if PBapp == 0:
                        continue

                    PGnow = self.stats['data_manager'][phi]['P']  # negative: drawing power from the grid
                    VGnow = self.stats['data_manager'][phi]['V']
                    Imax =  self.stats['data_manager'][phi]['Amax'] # eg. 25A main fuse
                    PGmax = abs(VGnow * Imax)
                    PBnow = sum(v['ac_side']['P'] for v in self.stats['inverters'].values() if v['phase'] == phi)  # total power of all inverters on phase

                    PBsent_phases[phi] = calc_PBsent(PBapp, PBnow, PGnow, VGnow, Imax, col_header=phi)

                    self.stats['inv_control'][phi] = {
                        'PBapp': PBapp,
                        'PBnow': PBnow,
                        'PGnow': PGnow,
                        'VGnow': VGnow,
                        'Imax': Imax,
                        'PGmax': PGmax,
                        'PGmin': -1 * PGmax,
                        'Pother': PGnow - PBnow,
                        'PBlim_min': -1 * PGmax - (PGnow - PBnow),
                        'PBlim_max': PGmax - (PGnow - PBnow),
                        'PBsent': PBsent_phases[phi],
                    }

                self.log.info(f'manual mode: sending charge/discharge amount (PBsent) to enabled inverters:')
                for phi, PBsent in PBsent_phases.items():
                    if PBsent < 0:  # negative: so charge
                        for inv_name in inv_phase_map[phi]:
                            self.log.info(f'commanding {inv_name} to charge at {PBsent:.0f} W')
                            await inverters.write_register(inv_name, 40149, to_s32_list(PBsent))
                    else:  # zero or positive: so discharge
                        for inv_name in inv_phase_map[phi]:
                            self.log.info(f'commanding {inv_name} to discharge at {PBsent:.0f} W')
                            await inverters.write_register(inv_name, 40149, to_s32_list(PBsent))

                await asyncio.sleep(self.config.get_general_config().get('loop_delay', 10))

            except asyncio.CancelledError:
                self.log.debug(f'mode 2 loop cancelled')
                raise

            finally:
                # make sure to relinquish control:
                await inverters.write_registers_parallel(40149, [0, 0])  # reset rendement
                await inverters.write_registers_parallel(40151, [0, 803])  # 803 = inactive

                inverters.close()
                dm.close()
                self.reset_stats()
                self.log.info(f'closed modbus connections')


    # Endpoint handlers
    @web.middleware
    async def filter_ingress_prefix(self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        resp = await handler(request)
        if not isinstance(resp, web.FileResponse):  # this middleware only acts on static file serving
            return resp
        if 'X-Ingress-Path' not in request.headers:  # no need to filter the static files as we are not running as a HA addon
            return resp

        filepath = (self._static_dir / request.path[1:]).resolve()
        self.log.debug(f'request: {request.path} -> filepath: {filepath}')
        if not filepath.exists():
            return web.Response(text='file not found', status=404)

        ingress_path = request.headers['X-Ingress-Path']
        self.log.debug(f'applying filters for ingress path: "{ingress_path}"')

        try:
            with filepath.open('rb') as f:
                buf = f.read()

            for m in get_ingress_filters(ingress_path):
                old = m[0].encode('utf-8')
                new = m[1].encode('utf-8')
                buf = buf.replace(old, new)

            with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as temp_file:
                temp_file.write(buf)

            modified_resp = web.FileResponse(temp_file.name)
            # FileResponse by default sets octet-stream as content-type. Apply correct header:
            modified_resp.headers['Content-Type'] = CONTENT_TYPE_MAP.get(filepath.suffix, 'application/octet-stream')
            return modified_resp
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    async def handle_root(self, request):
        return web.json_response({
            'status': 'ok',
            'running': self.sub_running,
            'running_start': self.sub_running_start,
            'mode': self.mode.value,
            'stats': self.stats,
        })

    async def handle_run(self, req):
        try:
            parsed = await req.json()
            if (
                not isinstance(parsed, dict) or
                'running' not in parsed or
                not isinstance(parsed['running'], bool)
            ):
                raise Exception(f'invalid running value: {parsed}')
            self.sub_running = parsed['running']

            # if sub_running is now false make sure the sub task is stopped
            if not self.sub_running:
                self.stop_sub_task()

            return web.json_response({'status': 'ok'})
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))
