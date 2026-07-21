import asyncio
import traceback
from datetime import datetime as dt

from config import ControlMode
from common import DMWException, PBSapp
from base_controller import BaseController


class Mode1Controller(BaseController):

    @property
    def mode(self) -> ControlMode:
        return ControlMode.IDLE

    def get_PBSapp(self, now: dt) -> PBSapp:
        # required by base class; unused in IDLE mode as there are no inverters being actively controlled
        return PBSapp(list(self.inverters.values()))

    async def loop(self):
        while self.running:  # outer, reconnect loop
            try:
                await self.connect_subsystems()
                await self.control_loop()

            except asyncio.CancelledError:
                self.log.info('mode 1 loop cancelled')
                self.stop()
            except DMWException as e:
                self.log.error(str(e))
                if e.requires_fallback:
                    self.stop()
            except Exception as e:
                self.log.fatal(f'encountered fatal error: {type(e).__name__}: {e}\n{traceback.format_exc()}')
                self.stop()

            self.close_subsystems()

            await self.reconnect_delay()

    async def control_loop(self):
        while self.running:  # inner, control loop

            # defensive re-assertion against state drift:
            self.log.info('idle: relinquish control for all inverters')
            await asyncio.gather(*[inv.relinquish_control() for inv in self.battery_inverters])
            await asyncio.gather(*[inv.relinquish_control() for inv in self.solar_inverters])

            await self.get_stats()

            await self.loop_delay()
