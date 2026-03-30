import asyncio
import json
from typing import Any, Optional
from datetime import datetime as dt, timedelta

from aiohttp import web

from config import DoeMaarWattConfig, ControlMode
from logger import Logger
from base_controller import BaseController
from modbus import ModbusManager
from price import PriceManager
from dyn_schedule import DynamicScheduler, SchedulePeriodEncoder


class Mode4Controller(BaseController):
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        super().__init__(cfg, log)

        self.price_task: Optional[asyncio.Task] = None  # type: ignore

        self.dyn_cfg: dict[str, Any] = cfg.get_mode_dynamic_config()
        self.update_interval = timedelta(seconds=self.dyn_cfg['update_interval'])
        self.pm: PriceManager = None  # type: ignore
        self.scheduler: DynamicScheduler = None  # type: ignore

    @property
    def mode(self) -> ControlMode:
        return ControlMode.DYNAMIC

    def setup(self) -> None:
        super().setup()

        # refresh key attributes:
        self.dyn_cfg = self.config.get_mode_dynamic_config()
        self.update_interval = timedelta(seconds=self.dyn_cfg['update_interval'])
        self.pm = PriceManager(self.config, self.log)
        self.scheduler = DynamicScheduler(self.config, self.pm)

        self.inv_capacities = self.config.get_inverter_field_map('battery_capacity')

    def _stop_price_loop_task(self):
        if self.price_task is not None:
            self.price_task.cancel()
            self.price_task = None

    def get_PBapp_phases(self, now: dt) -> dict[str, float]:
        '''Return a mapping of each phase (L1, L2, L3) to its associated PBapp. In mode 4 this entails using the computed schedule'''
        PBapp_inverters = self.scheduler.get_PBapp_inverters(now)  # inv -> PBapp

        ret = {}
        for phi, inverter_names in self.inv_phase_map.items():
            ret[phi] = sum(PBapp_inverters[inv] for inv in inverter_names)
        return ret

    async def loop(self):
        self.log.info(f'Mode 4 (dynamic schedule mode) started')

        while self.running:  # outer, reconnect loop:
            exception_occurred = False
            try:
                await self.pm.fetch_prices()
                self.price_task = asyncio.create_task(self.price_loop())
                self.log.info('fetched initial prices and started price update loop')

                self.inverters = ModbusManager(client_configs=self.inv_cfg, log=self.log)
                self.dm = ModbusManager(client_configs=[self.dm_cfg], log=self.log)
                await self.inverters.connect()
                await self.dm.connect()
                self.log.info(f'(re)connected to data manager and inverters')

                await self.control_loop()

            except asyncio.CancelledError:
                self.log.debug(f'mode 4 (dynamic schedule mode) loop cancelled')
                self.stop()  # running to false so outer loop exits cleanly
                self._stop_price_loop_task()
            except Exception as e:
                exception_occurred = True
                template = "An exception of type {0} occurred. Arguments:\n{1!r}"
                message = template.format(type(e).__name__, e.args)
                self.log.error(message)
                self._stop_price_loop_task()  # price task will be restarted on reconnect

            # an error or cancellation occurred: make sure to relinquish control:
            try:
                await self.inverters.write_registers_parallel(40149, [0, 0])  # reset rendement
                await self.inverters.write_registers_parallel(40151, [0, 803])  # 803 = inactive
            except Exception as e:
                self.log.error(f'encountered error while trying to send 803: {e}')
            finally:
                self.inverters.close()
                self.dm.close()
            self.log.info(f'closed modbus connections')

            # TODO trigger push notification (eg. using HA)

            # check if we need to fallback to a different mode:
            if exception_occurred and self.dyn_cfg['fallback_mode'] != self.config.mode:
                self.config.mode = self.config.get_mode_dynamic_config()['fallback_mode']
                return
            # otherwise we remain in mode 4 and try to reconnect:
            if self.running:
                await asyncio.sleep(10)  # wait 10 seconds before reconnecting

    async def control_loop(self):
        # inner, control loop
        while self.running:
            self.log.debug(f'mode 4 (dynamic schedule mode) control loop iteration started')

            # fetch current charge
            await self.inverters.write_registers_parallel(40151, [0, 802])  # 802 = active control
            current_charge = await self.get_current_charge()

            # determine if a schedule update is in order, and compute it if necessary based on currently available prices:
            now = dt.now(self.tz)
            if not self.scheduler.schedule_available_for(now) or now - self.scheduler.schedule_ts > self.update_interval:
                self.log.info(f'schedule update required (schedule age {now - self.scheduler.schedule_ts})')
                price_range = self.pm.get_price_range(now)
                self.log.info(f'updated prices: {len(price_range)} slots [{price_range[0][0].strftime("%H:%M")} — {price_range[-1][1].strftime("%H:%M")}]')

                self.scheduler.create_schedule(price_range[0][0], price_range[-1][0], current_charge)
                self.log.debug(f'determined optimal schedule for [{price_range[0][0].strftime("%H:%M")} — {price_range[-1][0].strftime("%H:%M")}] period')

            # schedule in place, so execute it by determing PBsent for each inverter:
            await self.command_PBsent(now)

            await asyncio.sleep(self.config.get_general_config().get('loop_delay', 10))

    async def get_current_charge(self) -> dict[str, float]:
        '''Using the modbus connections, retrieve the stats from the inverters and data manager. From those
        determine the current charge (in Wh) in each battery connected to an inverter and return it as a dict:

        inv_name -> charge_in_Wh
        '''
        await self.get_stats()
        self.log.debug(f'gathered stats - determining battery charges')

        ret = {}
        for inv_name, inv_stat in self.stats['inverters'].items():  # type: ignore
            charge_pct = inv_stat['battery']['charge']
            if charge_pct < 0 or charge_pct > 100:
                raise ValueError(f'charge percentage for inverter {inv_name} outside range: {charge_pct}')

            charge_wh = self.inv_capacities[inv_name] * charge_pct / 100.0
            if charge_pct < 1:
                self.log.debug(f'capacity for inverter {inv_name} indicated as {charge_pct:.1f} %, which implies a charge of {charge_wh} Wh')

            ret[inv_name] = charge_wh

        self.log.debug(f'battery charge status: ' + ', '.join(f'{i}: {c / 1e3:.1f} kWh' for i, c in ret.items()))
        return ret

    async def price_loop(self) -> None:
        '''Loop that performs daily price updates, synchronized to the configured `price_update_time` from the dynamic schedule mode configuration
        setting.'''
        loop_id = id(asyncio.current_task())
        while self.running:
            h, m = map(int, self.config.get_mode_dynamic_config()['price_update_time'].split(':'))

            now = dt.now(self.tz)
            next_update = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if next_update <= now:
                next_update += timedelta(days=1)

            sleep_seconds = (next_update - now).total_seconds()
            self.log.info(f'price_loop [{loop_id}]: next price update scheduled at {next_update.strftime("%Y-%m-%d %H:%M %Z")} (in {sleep_seconds:.0f}s)')
            self.log.info(self.scheduler.schedule_to_string())

            try:
                await asyncio.sleep(sleep_seconds)
            except asyncio.CancelledError:
                self.log.info(f'price_loop [{loop_id}]: cancelled')
                return
            if not self.running:
                break

            self.log.info(f'price_loop [{loop_id}]: fetching updated prices')
            await self.pm.fetch_prices()

    def handle_status(self, request):
        price_info = self.pm.to_dict()
        price_info['current_price'] = self.pm.get_price()

        return web.json_response({
            'status': 'ok',
            'running': self.running,
            'running_start': self.start_ts,
            'mode': self.mode.value,
            'stats': self.stats,
            'prices': price_info,
            'schedule': self.scheduler.schedule,
            'schedule_ts': self.scheduler.schedule_ts,
        }, dumps=lambda obj: json.dumps(obj, cls=SchedulePeriodEncoder))
