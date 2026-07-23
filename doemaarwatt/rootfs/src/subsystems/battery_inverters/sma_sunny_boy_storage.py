from typing import Any, Optional

from .base import BaseBatteryInverter, BatteryInverterStats, BatteryStatus, BatteryStats
from common import Logger, ModbusManager, to_s32_list, ControlStatus, Phase, SPCStats, ConfigException


_AC_REG_MAP = {
    Phase.L1: {'p': 30777, 'v': 30783, 'a': 30977},
    Phase.L2: {'p': 30779, 'v': 30785, 'a': 30979},
    Phase.L3: {'p': 30781, 'v': 30787, 'a': 30981},
}

# Commanding a zero charge/discharge power does not seem to work and relinquishes control of the battery inverter
# So instead when the schedule / user dictates that the battery inverter should remain standby, we command
# a very small charging power of 50 W
STANDBY_CHARGE = -50


class SmaSunnyBoyStorage(BaseBatteryInverter):

    def __init__(self,
        name: str,
        connected_phase: Phase,
        capacity_wh: int,
        charge_limit_w: int,
        discharge_limit_w: int,
        log: Logger,
        host: str,
        port: int = 502,
        charge_max_pct: float = 95.0,
        charge_min_pct: float = 10.0,
    ) -> None:
        super().__init__(name, connected_phase, capacity_wh, charge_limit_w, discharge_limit_w, log,
                         charge_max_pct=charge_max_pct, charge_min_pct=charge_min_pct)

        assert isinstance(connected_phase, Phase)
        if connected_phase == Phase.ALL:
            raise ConfigException('SMA Sunny Boy Storage only operates single phase', source=self.name)

        self._modbus = ModbusManager(
            client_configs=[{'name': name, 'host': host, 'port': port, 'enable': True}],
            log=log,
        )

    @classmethod
    def from_config(cls, cfg: dict[str, Any], log: Logger) -> 'SmaSunnyBoyStorage':
        return cls(
            name=cfg['name'],
            connected_phase=cfg['connected_phase'],
            capacity_wh=cfg['battery_capacity'],
            charge_limit_w=cfg['battery_charge_limit'],
            discharge_limit_w=cfg['battery_discharge_limit'],
            log=log,
            host=cfg['host'],
            port=cfg.get('port', 502),
            charge_max_pct=cfg.get('battery_charge_max_pct', 95.0),
            charge_min_pct=cfg.get('battery_charge_min_pct', 10.0),
        )

    async def connect(self) -> None:
        await self._modbus.connect()

    def close(self) -> None:
        self._modbus.close()

    async def enable_control(self) -> None:
        await self._modbus.write_registers_parallel(40151, [0, 802])

    async def relinquish_control(self) -> None:
        await self._modbus.write_registers_parallel(40149, [0, 0])
        await self._modbus.write_registers_parallel(40151, [0, 803])

    async def read_stats(self) -> BatteryInverterStats:

        temp_h = await self._modbus.read_register(self.name, 32221, 'S32', device_id=3, sma_format='TEMP')
        temp_l = await self._modbus.read_register(self.name, 32227, 'S32', device_id=3, sma_format='TEMP')
        charge = await self._modbus.read_register(self.name, 32233, 'U32', device_id=3, sma_format='FIX2')
        voltage = await self._modbus.read_register(self.name, 30851, 'U32', device_id=3, sma_format='FIX2')
        current = await self._modbus.read_register(self.name, 30843, 'S32', device_id=3, sma_format='FIX3')
        if charge is not None:
            charge *= 10  # fix for now

        registers = _AC_REG_MAP[self.connected_phase]
        ac_pow = await self._modbus.read_register(self.name, registers['p'], 'S32', device_id=3, sma_format='FIX0')
        ac_vol = await self._modbus.read_register(self.name, registers['v'], 'U32', device_id=3, sma_format='FIX2')
        ac_amp = await self._modbus.read_register(self.name, registers['a'], 'S32', device_id=3, sma_format='FIX3')

        bat_status = BatteryStatus.STANDBY
        if charge is None:
            bat_status = BatteryStatus.DISCONNECTED
        elif ac_pow is not None and ac_pow < 0:
            bat_status = BatteryStatus.CHARGING
        elif ac_pow is not None and ac_pow > 0:
            bat_status = BatteryStatus.DISCHARGING

        control_status = ControlStatus.DEGRADED if any(
            v is None for v in [temp_h, temp_l, voltage, current, ac_pow, ac_vol, ac_amp]
        ) else ControlStatus.NOMINAL

        self.log.debug(f'{self.name} (connected to {self.connected_phase}):')
        if current is None or voltage is None or ac_amp is None or ac_vol is None or ac_pow is None:
            self.log.error(f'\tbattery:\t{current} A\t{voltage} V\t{bat_status}\t - \t{temp_l} {chr(176)}C - {temp_h} {chr(176)}C')
            self.log.error(f'\tAC side:\t{ac_amp} A\t{ac_vol} V\t{ac_pow} W')
        else:
            if charge is None:
                self.log.debug(f'\tbattery:\t{current:.2f} A\t{voltage:.1f} V\t{bat_status}\t - \t{temp_l} {chr(176)}C - {temp_h} {chr(176)}C')
            else:
                self.log.debug(f'\tbattery:\t{current:.2f} A\t{voltage:.1f} V\t{bat_status}\t{charge:.1f} %\t{temp_l} {chr(176)}C - {temp_h} {chr(176)}C')
            self.log.debug(f'\tAC side:\t{ac_amp:.2f} A\t{ac_vol:.1f} V\t{ac_pow:.0f} W')

        return BatteryInverterStats(
            control_status=control_status,
            battery=BatteryStats(
                battery_status=bat_status,
                battery_current=current,
                battery_voltage=voltage,
                battery_charge_pct=charge,
                battery_temp_low_c=temp_l,
                battery_temp_high_c=temp_h,
            ),
            ac_side={ self.connected_phase: SPCStats(current=ac_amp, voltage=ac_vol, power=ac_pow) }
        )

    async def set_power(self, power_w: float) -> None:
        power_w = int(power_w)
        if power_w == 0:
            power_w = STANDBY_CHARGE

        await self._modbus.write_register(self.name, 40149, to_s32_list(power_w))

    async def read_charge_wh(self) -> Optional[float]:
        charge_pct = await self._modbus.read_register(self.name, 32233, 'U32', device_id=3, sma_format='FIX2')
        if charge_pct is None:
            return None
        return self.capacity_wh * (charge_pct * 10) / 100.0
