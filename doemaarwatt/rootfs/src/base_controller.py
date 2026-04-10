from abc import ABC, abstractmethod
import time
from datetime import datetime as dt, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo
import os

from aiohttp import web
import aiohttp

from config import DoeMaarWattConfig, ControlMode
from modbus import ModbusManager, to_s32_list
from logger import Logger
from stats import DM
from pbsent import calc_PBsent, STANDBY_CHARGE
from stats import battery_stats, data_manager_stats


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
        self.inv_cfg: list[dict[str, Any]] = None  # type: ignore
        self.dm_cfg: dict[str, Any] = None  # type: ignore

        self.inv_phase_map: dict[str, list[str]] = None  # type: ignore

        self.tz : ZoneInfo = None  # type: ignore

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

        self.inv_phase_map = self.config.get_phase_inverters_map()

        self.tz = ZoneInfo(self.config.timezone)

    async def run(self) -> None:
        self.running = True
        self.start_ts = time.time()

        self.setup()

        await self.loop()  # must be implemented by the concrete subclass

    @abstractmethod
    def get_PBapp_phases(self, now: dt) -> dict[str, float]:
        '''Return a mapping of each phase (L1, L2, L3) to its associated PBapp'''
        raise NotImplementedError

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

    async def get_stats(self):
        self.stats['inverters'] = await battery_stats(self.inverters, self.config.get_inverter_phase_map())  # type: ignore
        self.stats['data_manager'] = await data_manager_stats(self.dm, self.dm_cfg.get('max_fuse_current', 25))  # type: ignore

    async def command_PBsent(self, now: dt) -> None:
        self.log.info(f'computing safe charge/discharge amount (PBsent) for each phase:')
        PBapp_phases = self.get_PBapp_phases(now)
        PBsent_phases = {}
        self.stats['inv_control'] = {}  # type: ignore
        for phi in ['L1', 'L2', 'L3']:
            PBapp = PBapp_phases[phi]
            PGnow = self.stats['data_manager'][phi]['P']  # type: ignore | negative value: drawing power from the grid
            VGnow = self.stats['data_manager'][phi]['V']  # type: ignore
            Imax =  self.stats['data_manager'][phi]['Amax']  # type: ignore | eg. 25A main fuse
            PGmax = abs(VGnow * Imax)
            # compute PBnow: total power of all inverters on phase
            PBnow = sum(v['ac_side']['P'] for v in self.stats['inverters'].values() if v['phase'] == phi)  # type: ignore

            PBsent_phases[phi] = calc_PBsent(PBapp, PBnow, PGnow, VGnow, Imax, col_header=phi)

            self.stats['inv_control'][phi] = {
                'PBapp': PBapp, 'PBnow': PBnow, 'PGnow': PGnow,'VGnow': VGnow, 'Imax': Imax,
                'PGmin': -1 * PGmax, 'PGmax': PGmax,
                'Pother': PGnow - PBnow,
                'PBlim_min': -1 * PGmax - (PGnow - PBnow), 'PBlim_max': PGmax - (PGnow - PBnow),
                'PBsent': PBsent_phases[phi],
            }

        self.log.info(f'sending charge/discharge amount (PBsent) to enabled inverters:')
        for phi, PBsent in PBsent_phases.items():
            if PBsent == STANDBY_CHARGE:  # standby charge
                for inv_name in self.inv_phase_map[phi]:
                    self.log.info(f'commanding {inv_name} to do a standby charge at {PBsent:.0f} W')
                    await self.inverters.write_register(inv_name, 40149, to_s32_list(PBsent))
            elif PBsent < 0:  # negative: so charge
                for inv_name in self.inv_phase_map[phi]:
                    self.log.info(f'commanding {inv_name} to charge at {PBsent:.0f} W')
                    await self.inverters.write_register(inv_name, 40149, to_s32_list(PBsent))
            elif PBsent > 0:  # positive: so discharge
                for inv_name in self.inv_phase_map[phi]:
                    self.log.info(f'commanding {inv_name} to discharge at {PBsent:.0f} W')
                    await self.inverters.write_register(inv_name, 40149, to_s32_list(PBsent))
            else:
                raise ValueError(f'PBsent for phase {phi} is zero Watts which should not be possible')

    def handle_status(self, request):
        return web.json_response({
            'status': 'ok',
            'running': self.running,
            'running_start': self.start_ts,
            'mode': self.mode.value,
            'stats': self.stats,
            'prices': None,
            'schedule': None,
            'schedule_ts': None,
        })

    async def send_ha_notification(self, title: str, message: str):
        # prime method: use the SUPERVISOR_TOKEN (only available in production setup)
        token = os.environ.get('SUPERVISOR_TOKEN')
        url = 'http://supervisor/core/api/services/notify/persistent_notification'
        if not token:
            self.log.info(f'SUPERVISOR_TOKEN unavailable: falling back to manually created token')
            token = self.config.get_general_config()['supervisor_token']
            url = 'http://homeassistant:8123/api/services/notify/persistent_notification'

            if not token:
                self.log.error(f'No long-lived access token defined: unable to send push notification')
                return

        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={'title': title, 'message': message}, headers=headers)

        except Exception as e:
            self.log.error(f'unable to send HA notification: {e}')
