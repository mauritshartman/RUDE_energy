import asyncio
import traceback
from typing import Any
from datetime import time, datetime as dt

from config import DoeMaarWattConfig, ControlMode
from common import Logger, DMWException, PBSapp
from base_controller import BaseController


class Mode3Controller(BaseController):
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        super().__init__(cfg, log)

        self.schedule: list[dict[str, Any]] = []

    @property
    def mode(self) -> ControlMode:
        return ControlMode.STATIC

    def setup(self) -> None:
        super().setup()

        static_cfg = self.config.get_mode_static_config()
        self.schedule = []
        for t in static_cfg['schedule']:
            entry: dict[str, Any] = {
                'time': time.fromisoformat(t['time']),
                'solar_amount': abs(t.get('solar_amount', 0.0)),
            }

            if t['direction'] in ['idle', 'standby']:
                entry['battery_amount'] = 0.0
            elif t['direction'] == 'charge':
                entry['battery_amount'] = -1 * abs(t['battery_amount'])  # ensure negative amount value for charging
            else:
                entry['battery_amount'] = abs(t['battery_amount'])  # ensure positive amount value for charging

            self.schedule.append(entry)
        self.schedule.sort(key=lambda t: t['time'])  # sort by time ascending

    def get_PBSapp(self, now: dt) -> PBSapp:
        '''Return the desired power level (PBSapp) for each controlled inverter based on the active static
        schedule entry: every battery inverter is commanded the entry's battery amount and every solar
        inverter its solar amount, on the phase(s) it is connected to.'''
        cur_time = now.time()

        bat_charge_amount = 0.0  # default: idle (if no schedule entries are defined)
        sol_charge_amount = 0.0
        if len(self.schedule) > 0:
            active = self.schedule[-1]  # base entry is last schedule change of the day (wraps around)
            for t in self.schedule:
                if cur_time >= t['time']:
                    active = t
                else:
                    break
            bat_charge_amount = active['battery_amount']
            sol_charge_amount = active['solar_amount']
        self.log.debug(f'determined PBapp to be battery={bat_charge_amount}W, solar={sol_charge_amount}W '
                       f'based on static schedule (time {cur_time})')

        pbsapp = PBSapp(list(self.inverters.values()))
        for inv in self.battery_inverters:
            pbsapp.set(inv.connected_phase, inv.name, bat_charge_amount)
        for inv in self.solar_inverters:
            # solar_amount is per-phase: it is applied to each connected phase (so an ALL-connected
            # inverter's total commanded output is solar_amount * number of phases)
            pbsapp.set(inv.connected_phase, inv.name, sol_charge_amount)

        return pbsapp

    async def _try_relinquish_control(self):
        results = await asyncio.gather(*[inv.relinquish_control() for inv in self.battery_inverters],
                                           return_exceptions=True)
        for inv, result in zip(self.battery_inverters, results):
            if isinstance(result, Exception):
                self.log.error(f'error relinquishing control of {inv.name}: {result}')
        results = await asyncio.gather(*[inv.relinquish_control() for inv in self.solar_inverters],
                                        return_exceptions=True)
        for inv, result in zip(self.solar_inverters, results):
            if isinstance(result, Exception):
                self.log.error(f'error relinquishing control of {inv.name}: {result}')

    async def loop(self):
        self.log.info(f'Mode 3 (static schedule mode) started')
        while self.running:  # outer, reconnect loop:
            try:
                await self.connect_subsystems()
                await self.control_loop()

            except asyncio.CancelledError:
                self.log.debug(f'mode 3 loop cancelled')
                self.stop()
            except DMWException as e:
                self.log.error(str(e))
                if e.requires_fallback:
                    self.stop()
            except Exception as e:
                self.log.error(f'encountered fatal error: {type(e).__name__}: {e}\n{traceback.format_exc()}')
                self.stop()

            # an error or cancellation occurred: make sure to relinquish control:
            await self._try_relinquish_control()
            self.close_subsystems()

            await self.reconnect_delay()

    async def control_loop(self):
        # inner, control loop
        while self.running:
            self.log.debug(f'mode 3 control loop started')
            await asyncio.gather(*[inv.enable_control() for inv in self.battery_inverters])
            await asyncio.gather(*[inv.enable_control() for inv in self.solar_inverters])

            # get necessary stats and determine PBsent for each phase
            await self.get_stats()
            await self.command_PBSsent(dt.now(tz=self.tz))

            await self.loop_delay()
