import asyncio
import signal
import os
import time
import json
from aiohttp import web
import aiohttp_cors

from modbus import ModbusManager, to_s32_list
from config import DoeMaarWattConfig, ControlMode
from stats import DM, battery_stats, data_manager_stats
from pbsent import calc_PBsent


API_SERVER_PORT = 8080


class DoeMaarWattServer:
    def __init__(self) -> None:
        # control related variables
        self.config = DoeMaarWattConfig()
        self.mode = self.config.mode  # use configured startup mode

        # webserver related:
        self.app = web.Application()
        self.setup_app()
        self.main_task: asyncio.Task = None
        self.sub_task: asyncio.Task = None
        self.running = True  # for main control loop
        self.sub_running = self.config.autostart  # for sub control loop
        self.sub_running_start = None
        self.reset_stats()

        def sig_handler(sig, frame):
            print(f'\nSIGINT received')
            self.stop()
        signal.signal(signal.SIGINT, sig_handler)

    def setup_app(self) -> None:
        self.app.router.add_get('/', self.handle_root)
        self.app.router.add_post('/run', self.handle_run)
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
        site = web.TCPSite(runner, 'localhost', API_SERVER_PORT)
        await site.start()
        print(f'backend webserver started on {API_SERVER_PORT}')

        while self.running:  # will only be stopped by a stop() / SIGINT
            try:
                print(f'waiting for running to become true')
                while not self.sub_running:  # busy waiting until sub_task can start running
                    await asyncio.sleep(0.25)

                self.mode = self.config.mode  # use configured startup mode
                print(f'we are running: determined startup mode {self.mode}')
                if self.mode == ControlMode.IDLE:
                    self.sub_task = asyncio.create_task(self.mode_1_loop())
                elif self.mode == ControlMode.MANUAL:
                    self.sub_task = asyncio.create_task(self.mode_2_loop())

                self.sub_running_start = time.time()
                await self.sub_task

            except asyncio.CancelledError:
                print('main control loop handling cancel')
                self.stop_sub_task()

        await runner.cleanup()
        print(f'backend webserver stopped')

    def reset_stats(self):
        self.stats = {
            'inverters': None,
            'data_manager': None,
            'inv_control': None,
        }

    async def mode_1_loop(self):
        print(f'mode 1 loop started')

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

                print(f'idle: relinquish control and reset power set point')
                await inverters.write_registers_parallel(40149, [0, 0])  # reset rendement
                await inverters.write_registers_parallel(40151, [0, 803])  # 803 = inactive

                self.stats['inverters'] = await battery_stats(inverters, self.config.get_inverter_phase_map())
                self.stats['data_manager'] = await data_manager_stats(dm, dm_cfg.get('max_fuse_current', 25))

                await asyncio.sleep(self.config.get_general_config().get('loop_delay', 10))
            except asyncio.CancelledError:
                print(f'mode 1 loop cancelled')
                raise
            finally:
                inverters.close()
                dm.close()
                self.reset_stats()
                print(f'closed modbus connections')

    async def mode_2_loop(self):
        print(f'Mode 2 (manual mode) started')

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
                print(f'manual mode: computing safe charge/discharge amount (PBsent) for each phase:')
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

                print(f'manual mode: sending charge/discharge amount (PBsent) to enabled inverters:')
                for phi, PBsent in PBsent_phases.items():
                    if PBsent < 0:  # negative: so charge
                        for inv_name in inv_phase_map[phi]:
                            print(f'commanding {inv_name} to charge at {PBsent:.0f} W')
                            await inverters.write_register(inv_name, 40149, to_s32_list(PBsent))
                    else:  # zero or positive: so discharge
                        for inv_name in inv_phase_map[phi]:
                            print(f'commanding {inv_name} to discharge at {PBsent:.0f} W')
                            await inverters.write_register(inv_name, 40149, to_s32_list(PBsent))

                await asyncio.sleep(self.config.get_general_config().get('loop_delay', 10))

            except asyncio.CancelledError:
                print(f'mode 2 loop cancelled')
                raise

            finally:
                # make sure to relinquish control:
                await inverters.write_registers_parallel(40149, [0, 0])  # reset rendement
                await inverters.write_registers_parallel(40151, [0, 803])  # 803 = inactive

                inverters.close()
                dm.close()
                self.reset_stats()
                print(f'closed modbus connections')


    # Endpoint handlers
    async def handle_root(self, request):
        print(request.headers)
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
