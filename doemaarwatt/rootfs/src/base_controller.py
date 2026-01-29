from abc import ABC, abstractmethod
import time

from aiohttp import web

from config import DoeMaarWattConfig, ControlMode
from modbus import ModbusManager
from logger import Logger
from stats import DM


class BaseController(ABC):
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        self.config = cfg
        self.log = log

        self.running = False
        self.start_ts = None
        self.reset_stats()

        # data manager and inverter config: will be updated by setup()
        self.inverters: ModbusManager
        self.dm: ModbusManager
        self.inv_cfg = None
        self.dm_cfg = None

    def reset_stats(self) -> None:
        self.start_ts = None
        self.stats = {
            'inverters':    None,
            'data_manager': None,
            'inv_control':  None,
        }

    @property
    def mode(self) -> ControlMode:
        '''
        :return: The control mode implemented by this controller
        :rtype: ControlMode
        '''
        raise NotImplementedError

    def stop(self) -> None:
        self.running = False
        self.reset_stats()

    def setup(self) -> None:
        self.inv_cfg = self.config.get_inverters_config()
        self.dm_cfg = self.config.get_data_manager_config()
        if len(self.dm_cfg) > 0:
            self.dm_cfg['name'] = DM

    async def run(self) -> None:
        self.running = True
        self.start_ts = time.time()

        self.setup()

        await self.loop()  # must be implemented by the concrete subclass

    @abstractmethod
    async def loop(self) -> None:
        '''
        Main control loop of the controller. Assumes that setup() has been called.
        Is implemented by the concrete control algorithm. Should stop when either:
        - self.running becomes False
        - this task is canceled

        :param self: Description
        '''
        raise NotImplementedError

    def handle_status(self, request):
        return web.json_response({
            'status': 'ok',
            'running': self.running,
            'running_start': self.start_ts,
            'mode': self.mode.value,
            'stats': self.stats,
        })
