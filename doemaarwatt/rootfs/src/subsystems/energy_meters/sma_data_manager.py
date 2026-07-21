from typing import Any

from prettytable import PrettyTable

from common import Logger, ModbusManager, ControlStatus, Phase, SPCStats
from .base import BaseEnergyMeter, EnergyMeterStats, _phase_status


DEVICE_ID = 2  # SMA Data Manager Modbus device ID


class SmaDataManager(BaseEnergyMeter):

    def __init__(self, name: str, max_fuse_a: int, host: str, port: int, log: Logger) -> None:
        super().__init__(name, max_fuse_a, log)
        self._modbus = ModbusManager(
            client_configs=[{'name': name, 'host': host, 'port': port, 'enable': True}],
            log=log,
        )

    @classmethod
    def from_config(cls, cfg: dict[str, Any], log: Logger) -> 'SmaDataManager':
        return cls(
            name=cfg.get('name', 'Data Manager'),
            max_fuse_a=cfg.get('max_fuse_current', 25),
            host=cfg['host'],
            port=cfg.get('port', 502),
            log=log,
        )

    async def connect(self) -> None:
        await self._modbus.connect()

    def close(self) -> None:
        self._modbus.close()

    async def read_stats(self) -> EnergyMeterStats:
        self.log.debug('reading data manager properties:')

        l1_current = await self._modbus.read_register(self.name, 31535, 'S32', device_id=DEVICE_ID, sma_format='FIX3')
        l2_current = await self._modbus.read_register(self.name, 31537, 'S32', device_id=DEVICE_ID, sma_format='FIX3')
        l3_current = await self._modbus.read_register(self.name, 31539, 'S32', device_id=DEVICE_ID, sma_format='FIX3')

        l1_voltage = await self._modbus.read_register(self.name, 31529, 'U32', device_id=DEVICE_ID, sma_format='FIX2')
        l2_voltage = await self._modbus.read_register(self.name, 31531, 'U32', device_id=DEVICE_ID, sma_format='FIX2')
        l3_voltage = await self._modbus.read_register(self.name, 31533, 'U32', device_id=DEVICE_ID, sma_format='FIX2')

        l1_power = await self._modbus.read_register(self.name, 31503, 'S32', device_id=DEVICE_ID, sma_format='FIX0')
        l2_power = await self._modbus.read_register(self.name, 31505, 'S32', device_id=DEVICE_ID, sma_format='FIX0')
        l3_power = await self._modbus.read_register(self.name, 31507, 'S32', device_id=DEVICE_ID, sma_format='FIX0')

        mf = self.max_fuse_a
        table = PrettyTable()
        table.add_column('', ['Current', 'Max Current', 'Voltage', 'Power', 'Status'])
        for label, current, voltage, power in [
            ('L1', l1_current, l1_voltage, l1_power),
            ('L2', l2_current, l2_voltage, l2_power),
            ('L3', l3_current, l3_voltage, l3_power),
        ]:
            if current is None or voltage is None or power is None:
                table.add_column(label, [str(current), f'{mf} A', str(voltage), str(power), _phase_status(power)])
            else:
                table.add_column(label, [f'{current:.2f}', f'{mf} A', f'{voltage:.1f} V', f'{power:.0f} W', _phase_status(power)])
            table.align[label] = 'r'
        self.log.debug(str(table))

        control_status = ControlStatus.DEGRADED if any(v is None for v in [
            l1_current, l2_current, l3_current,
            l1_voltage, l2_voltage, l3_voltage,
            l1_power, l2_power, l3_power,
        ]) else ControlStatus.NOMINAL

        return EnergyMeterStats(
            control_status=control_status,
            max_fuse_a=self.max_fuse_a,
            grid={
                Phase.L1: SPCStats(power=l1_power, current=l1_current, voltage=l1_voltage),
                Phase.L2: SPCStats(power=l2_power, current=l2_current, voltage=l2_voltage),
                Phase.L3: SPCStats(power=l3_power, current=l3_current, voltage=l3_voltage),
            },
        )
