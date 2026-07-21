import asyncio
import traceback
from datetime import datetime as dt

from config import DoeMaarWattConfig, ControlMode
from common import Logger, DMWException, PBSapp
from base_controller import BaseController


class Mode2Controller(BaseController):
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        super().__init__(cfg, log)

        self.bat_charge_amount = 0.0
        self.sol_charge_amount = 0.0

    @property
    def mode(self) -> ControlMode:
        return ControlMode.MANUAL

    def setup(self) -> None:
        super().setup()

        manual_cfg = self.config.get_mode_manual_config()

        self.bat_charge_amount = manual_cfg.get('battery_amount', 0.0)
        direction = manual_cfg.get('direction', 'standby')
        if direction in ['idle', 'standby']:
            self.bat_charge_amount = 0.0  # ensure amount is set to zero in standby mode
        elif direction == 'charge':
            self.bat_charge_amount = -1 * abs(self.bat_charge_amount)  # ensure negative value for charging
        else:
            self.bat_charge_amount = abs(self.bat_charge_amount)  # ensure positive value for discharging

        # ensure positive value for solar (can only source power)
        self.sol_charge_amount = abs(manual_cfg.get('solar_amount', 0.0))

    def get_PBSapp(self, now: dt) -> PBSapp:
        '''Return the desired power level (PBSapp) for each controlled inverter. In manual mode every
        battery inverter is commanded the configured fixed battery amount and every solar inverter the
        configured fixed solar amount, on the phase(s) it is connected to.'''
        pbsapp = PBSapp(list(self.inverters.values()))

        for inv in self.battery_inverters:
            pbsapp.set(inv.connected_phase, inv.name, self.bat_charge_amount)
        for inv in self.solar_inverters:
            # solar_amount is per-phase: it is applied to each connected phase (so an ALL-connected
            # inverter's total commanded output is solar_amount * number of phases)
            pbsapp.set(inv.connected_phase, inv.name, self.sol_charge_amount)

        return pbsapp

    async def loop(self):
        self.log.info('Mode 2 (manual mode) started')
        while self.running:  # outer, reconnect loop:
            try:
                await self.connect_subsystems()
                await self.control_loop()

            except asyncio.CancelledError:
                self.log.debug('mode 2 loop cancelled')
                self.stop()
            except DMWException as e:
                self.log.error(str(e))
                if e.requires_fallback:
                    self.stop()
            except Exception as e:
                self.log.fatal(f'encountered fatal error: {type(e).__name__}: {e}\n{traceback.format_exc()}')
                self.stop()

            # an error or cancellation occurred: make sure to relinquish control:
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

            self.close_subsystems()

            await self.reconnect_delay()

    async def control_loop(self):
        # inner, control loop
        while self.running:
            self.log.debug('mode 2 control loop started')
            await asyncio.gather(*[inv.enable_control() for inv in self.battery_inverters])
            await asyncio.gather(*[inv.enable_control() for inv in self.solar_inverters])

            # get necessary stats and determine PBsent for each phase
            await self.get_stats()
            await self.command_PBSsent(dt.now(tz=self.tz))

            await self.loop_delay()
