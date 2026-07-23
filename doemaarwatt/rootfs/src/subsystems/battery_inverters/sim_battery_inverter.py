import asyncio
from typing import Any, Optional
import random
import time

from .base import BaseBatteryInverter, BatteryInverterStats, BatteryStats, BatteryStatus
from common import Logger, ControlStatus, Phase, SPCStats, SINGLE_PHASES


IO_LATENCY = 0.1 # simulated IO delay
STANDBY_CHARGE = -50  # small standby charge power (W) applied instead of idling at 0 W (mirrors the SMA driver)


class SimBatteryInverter(BaseBatteryInverter):

    def __init__(self,
        name: str,
        connected_phase: Phase,
        capacity_wh: int,
        charge_limit_w: int,
        discharge_limit_w: int,
        log: Logger,
        charge_max_pct: float = 95.0,
        charge_min_pct: float = 10.0,
    ) -> None:
        super().__init__(name, connected_phase, capacity_wh, charge_limit_w, discharge_limit_w, log,
                         charge_max_pct=charge_max_pct, charge_min_pct=charge_min_pct)

        self.is_connected = False
        self.is_controlled = False

        self.charge_power = 0.0
        self.current_charge_wh: Optional[float] = None
        self.last_read_ts = time.time()

        self.temp = random.uniform(19.0, 21.0)
        self.temp_l = self.temp
        self.temp_h = self.temp

    @classmethod
    def from_config(cls, cfg: dict[str, Any], log: Logger) -> 'SimBatteryInverter':
        return cls(
            name=cfg['name'],
            connected_phase=cfg['connected_phase'],
            capacity_wh=cfg['battery_capacity'],
            charge_limit_w=cfg['battery_charge_limit'],
            discharge_limit_w=cfg['battery_discharge_limit'],
            log=log,
            charge_max_pct=cfg.get('battery_charge_max_pct', 95.0),
            charge_min_pct=cfg.get('battery_charge_min_pct', 10.0),
        )

    async def _io_delay(self):
        await asyncio.sleep(random.uniform(0.9 * IO_LATENCY, 1.1 * IO_LATENCY))

    def _simulate_temperature(self):
        new_temp = random.uniform(19.0, 21.0)
        self.temp_l = min(new_temp, self.temp)
        self.temp_h = max(new_temp, self.temp)
        self.temp = new_temp

    async def connect(self) -> None:
        await self._io_delay()

        self.is_connected = True
        self.charge_power = 0.0
        self.current_charge_wh = random.uniform(0.0, self.capacity_wh) # random charge at startup

        self._simulate_temperature()

        self.last_read_ts = time.time()

    def close(self) -> None:
        self.is_connected = False
        self.is_controlled = False
        self.charge_power = 0.0
        self.current_charge_wh = None

    async def enable_control(self) -> None:
        await self._io_delay()

        # Only reset to a safe 0 on the transition into controlled state. The control
        # loop calls enable_control() every iteration; resetting unconditionally would
        # wipe the commanded charge_power before read_stats() captures it, so the
        # simulated inverter would always report standby. (A real inverter's
        # enable_control only writes the control-mode register and never resets power.)
        if not self.is_controlled:
            self.charge_power = 0.0
        self.is_controlled = True

    async def relinquish_control(self) -> None:
        self.is_controlled = False
        self.charge_power = 0.0

        await self._io_delay()

    def _simulate_charge_power(self):
        '''
        Simulate the effect of the application of (dis)charging power for a given duration
        '''
        if self.current_charge_wh is None:
            return

        now = time.time()
        lapsed_hours = (now - self.last_read_ts) / 3600.0
        self.last_read_ts = now

        if self.charge_power == 0: # battery has been standby, so no change in current charge or charging power
            return

        if self.charge_power < 0: # battery has been commanded to charge for the past lapsed hours
            in_charge_wh = abs(self.charge_power) * lapsed_hours
            new_charge_wh = self.current_charge_wh + in_charge_wh
            if new_charge_wh > self.capacity_wh: # charging would exceed capacity, so clamp at capacity at set charge power to zero
                self.current_charge_wh = self.capacity_wh
                self.charge_power = 0.0
            else:
                self.current_charge_wh = new_charge_wh

        else: # charge_power > 0, battery has been commanded to discharge for the past lapsed hours
            out_charge_wh = abs(self.charge_power) * lapsed_hours
            new_charge_wh = self.current_charge_wh - out_charge_wh
            if new_charge_wh < 0.0: # discharging would drain battery below zero, so clamp at zero at set discharge power to zero
                self.current_charge_wh = 0.0
                self.charge_power = 0.0
            else:
                self.current_charge_wh = new_charge_wh

    async def read_stats(self) -> BatteryInverterStats:
        await self._io_delay()

        # simulate battery charging / discharging and temperatures
        self._simulate_charge_power() # also updates last_read_ts
        self._simulate_temperature()

        # simulate battery status
        bat_status = BatteryStatus.STANDBY
        if not self.is_connected:
            bat_status = BatteryStatus.DISCONNECTED
        elif self.charge_power < 0:
            bat_status = BatteryStatus.CHARGING
        elif self.charge_power > 0:
            bat_status = BatteryStatus.DISCHARGING

        # simulate AC and DC voltages, currents and power:
        ac_vol = random.uniform(220.0, 240.0)
        ac_pow = self.charge_power * 1.01 # 1% internal power consumption by the inverter
        ac_amp = ac_pow / ac_vol
        voltage = random.uniform(400.0, 420.0)
        current = self.charge_power / voltage
        charge_pct = None if self.current_charge_wh is None else self.current_charge_wh / self.capacity_wh * 100.0

        ac_side_stats: dict[Phase, SPCStats] = {}
        if self.connected_phase.is_single_phase:
            ac_side_stats[self.connected_phase] = SPCStats(voltage=ac_vol, current=ac_amp, power=ac_pow)
        else:
            for phi in SINGLE_PHASES:
                ac_side_stats[phi] = SPCStats(voltage=ac_vol, current=ac_amp / 3.0, power=ac_pow / 3.0)

        return BatteryInverterStats(
            control_status=ControlStatus.NOMINAL if self.is_controlled else ControlStatus.UNCONTROLLED,
            battery=BatteryStats(
                battery_status=bat_status,
                battery_current=current,
                battery_voltage=voltage,
                battery_charge_pct=charge_pct,
                battery_temp_low_c=self.temp_l,
                battery_temp_high_c=self.temp_h,
            ),
            ac_side=ac_side_stats,
        )

    async def set_power(self, power_w: float) -> None:
        await self._io_delay()

        # mirror the real SMA inverter: commanding exactly 0 W relinquishes control and lets the inverter
        # idle, so a small standby charge power is applied instead to keep it awake (see sma_sunny_boy_storage)
        if power_w == 0:
            power_w = STANDBY_CHARGE

        if power_w < 0: # charging
            self.charge_power = max(power_w, self.charge_limit_w)
        elif power_w >= 0: # idle or discharging
            self.charge_power = min(power_w, self.discharge_limit_w)

    async def read_charge_wh(self) -> float | None:
        await self._io_delay()

        self._simulate_charge_power()
        return self.current_charge_wh
