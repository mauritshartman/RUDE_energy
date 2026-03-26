import asyncio
from typing import Any, Optional
from datetime import time, datetime as dt, timezone, timedelta

from config import DoeMaarWattConfig, ControlMode
from logger import Logger
from base_controller import BaseController
from modbus import ModbusManager, to_s32_list
from pbsent import calc_PBsent
from stats import battery_stats, data_manager_stats


class Mode3Controller(BaseController):
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        super().__init__(cfg, log)

        self.inv_phase_map: dict[str, list[str]] = None  # type: ignore
        self.schedule: list[dict[str, Any]] = []

    @property
    def mode(self) -> ControlMode:
        return ControlMode.STATIC

    def setup(self) -> None:
        super().setup()

        static_cfg = self.config.get_mode_static_config()
        self.schedule = []
        for t in static_cfg['schedule']:
            entry: dict[str, Any] = { 'time': time.fromisoformat(t['time']) }
            if t['direction'] in ['idle', 'standby']:
                entry['amount'] = 0
            elif t['direction'] == 'charge':
                entry['amount'] = -1 * abs(t['amount'])  # ensure negative amount value for charging
            else:
                entry['amount'] = abs(t['amount'])  # ensure positive amount value for charging

            self.schedule.append(entry)
        self.schedule.sort(key=lambda t: t['time'])  # sort by time ascending

        self.inv_phase_map = self.config.get_phase_inverters_map()

    def get_PBapp_phases(self, now: dt) -> dict[str, float]:
        assert not self.inv_phase_map is None

        cur_time = now.time()

        charge_amount = 0  # default: idle (if no schedule entries are defined)
        if len(self.schedule) > 0:
            charge_amount = self.schedule[-1]['amount']  # base amount is last schedule change of the day
            for t in self.schedule:
                if cur_time >= t['time']:
                    charge_amount = t['amount']
                else:
                    break
        self.log.debug(f'determined PBapp to be {charge_amount}W based on static schedule (time {cur_time})')

        return {
            phase: (charge_amount if len(inv_names) > 0 else 0)
            for phase, inv_names
            in self.inv_phase_map.items()
        }

    async def loop(self):
        self.log.info(f'Mode 3 (static schedule mode) started')
        while self.running:  # outer, reconnect loop:
            try:
                self.inverters = ModbusManager(client_configs=self.inv_cfg, log=self.log)
                self.dm = ModbusManager(client_configs=[self.dm_cfg], log=self.log)
                await self.inverters.connect()
                await self.dm.connect()
                self.log.info(f'(re)connected to data manager and inverters')

                await self.control_loop()

            except asyncio.CancelledError:
                self.log.debug(f'mode 3 loop cancelled')
                self.stop()  # running to false so break out of inner loop
            except Exception as e:
                self.log.error(f'encountered error: {e}')
                self.stop()  # running to false so break out of inner loop

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

            if self.running:
                await asyncio.sleep(10)  # wait 10 seconds before reconnecting

    async def control_loop(self):
        # inner, control loop
        while self.running:
            self.log.debug(f'mode 3 control loop started')
            await self.inverters.write_registers_parallel(40151, [0, 802])  # 802 = active

            # get necessary stats and determine PBsent for each phase
            await self.get_stats()
            await self.command_PBsent(dt.now(tz=self.tz))

            await asyncio.sleep(self.config.get_general_config().get('loop_delay', 10))
