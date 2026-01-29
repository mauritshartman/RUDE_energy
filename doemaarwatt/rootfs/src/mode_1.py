import asyncio

from config import DoeMaarWattConfig, ControlMode
from logger import Logger
from base_controller import BaseController
from modbus import ModbusManager
from stats import battery_stats, data_manager_stats


class Mode1Controller(BaseController):
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        super().__init__(cfg, log)

    @property
    def mode(self) -> ControlMode:
        return ControlMode.IDLE

    async def loop(self):
        while self.running:  # outer, reconnect loop
            try:
                self.inverters = ModbusManager(client_configs=self.inv_cfg, log=self.log)
                self.dm = ModbusManager(client_configs=[self.dm_cfg], log=self.log)
                await self.inverters.connect()
                await self.dm.connect()
                self.log.info(f'(re)connected to data manager and inverters')

                await self.control_loop()

            except asyncio.CancelledError:
                self.log.info(f'mode 1 loop cancelled')
                self.stop()
            except Exception as e:
                self.log.error(f'encountered error: {e}')
                self.stop()

            self.inverters.close()
            self.dm.close()
            self.log.info(f'closed modbus connections')

            if self.running:
                await asyncio.sleep(10)  # wait 10 seconds before reconnecting

    async def control_loop(self):
        while self.running:  # inner, control loop
            self.log.info(f'idle: relinquish control and reset power set point')
            await self.inverters.write_registers_parallel(40149, [0, 0])  # reset rendement
            await self.inverters.write_registers_parallel(40151, [0, 803])  # 803 = inactive

            self.stats['inverters'] = await battery_stats(self.inverters, self.config.get_inverter_phase_map())
            self.stats['data_manager'] = await data_manager_stats(self.dm, self.dm_cfg.get('max_fuse_current', 25))

            await asyncio.sleep(self.config.get_general_config().get('loop_delay', 10))
