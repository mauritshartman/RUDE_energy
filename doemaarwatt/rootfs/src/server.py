import asyncio
import signal
import tempfile
from pathlib import Path
import json
from typing import Callable, Awaitable

from aiohttp import web
import aiohttp_cors

from config import DoeMaarWattConfig, ControlMode
from logger import Logger, LogLevel
from base_controller import BaseController
from mode_1 import Mode1Controller
from mode_2 import Mode2Controller
from mode_3 import Mode3Controller


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

CONTROLLER_MAP: dict[ControlMode, BaseController] = {
    ControlMode.IDLE: Mode1Controller,
    ControlMode.MANUAL: Mode2Controller,
    ControlMode.STATIC: Mode3Controller,
}


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

        self.controller: BaseController = None

        # webserver related:
        self.app = web.Application(middlewares=[self.filter_ingress_prefix])
        self.setup_app()
        self.main_task: asyncio.Task = None
        self.sub_task: asyncio.Task = None
        self.running = True  # for main control loop
        self.sub_running = self.config.autostart  # for sub control loop

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
        self.main_task = asyncio.create_task(self.main_loop())
        await asyncio.sleep(1)
        await self.main_task

    def stop(self) -> None:
        self.running = False
        if not self.main_task is None:
            self.main_task.cancel()
            self.main_task = None

    def stop_sub_task(self) -> None:
        self.sub_running = False
        if not self.controller is None:
            self.controller.stop()
        if not self.sub_task is None:
            self.sub_task.cancel()
            self.sub_task = None

    async def main_loop(self) -> None:
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
                self.controller = CONTROLLER_MAP[self.mode](self.config, self.log)
                self.log.info(f'we are running: determined startup mode {self.mode}')
                self.sub_task = asyncio.create_task(self.controller.run())
                await self.sub_task

            except asyncio.CancelledError:
                self.log.debug('main control loop handling cancel')
                self.stop_sub_task()

        await runner.cleanup()
        self.log.info(f'backend webserver stopped')

    # Endpoint handlers
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

    async def handle_root(self, request):
        if self.controller is None:
            return web.json_response({
                'status': 'ok',
                'running': False,  # no control loop active at the moment
                'running_start': None,
                'mode': self.mode.value,
                'stats': None,
            })
        else:
            return self.controller.handle_status(request)

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
