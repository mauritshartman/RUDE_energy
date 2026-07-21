from typing import Any

from common import Logger, ModbusManager, to_u32_list, to_s32_list, ControlStatus, Phase, SPCStats, ProgrammingError, ControlException
from .base import BaseSolarInverter, SolarInverterStats


class SmaSolarInverter(BaseSolarInverter):

    def __init__(self,
        name: str,
        connected_phase: Phase,
        log: Logger,
        host: str,
        port: int = 502,
        device_id: int = 3,
    ) -> None:
        super().__init__(name, connected_phase, log)

        assert isinstance(connected_phase, Phase)
        assert connected_phase == Phase.ALL, 'SMA TriPower solar inverter is 3-phase'

        self._device_id = device_id
        self._modbus = ModbusManager(
            client_configs=[{'name': name, 'host': host, 'port': port, 'enable': True}],
            log=log,
        )

        self.is_connected = False
        self.is_controlled = False

    @classmethod
    def from_config(cls, cfg: dict[str, Any], log: Logger) -> 'SmaSolarInverter':
        return cls(
            name=cfg.get('name', 'SMA STP X-25'),
            connected_phase=cfg.get('connected_phase', Phase.ALL),
            log=log,
            host=cfg['host'],
            port=cfg.get('port', 502),
            device_id=cfg.get('modbus_device_id', 3),
        )

    @property
    def power_limits_phase(self) -> tuple[float, float]:
        return (
            0.0, # solar inverter can only source power, not sink it
            25_000 / 3.0,
        )

    async def connect(self) -> None:
        await self._modbus.connect()
        self.is_connected = True

    def close(self) -> None:
        self.is_controlled = False
        self.is_connected = False

        self._modbus.close()

    async def enable_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to assert control, not connected', source=self.name)

        # Parameter.Inverter.WModCfg.WCtlComCfg.Ena, 308 = ON (potentially needed as enable switch for external control channel
        await self._modbus.write_register(self.name, 41383, to_u32_list(308), device_id=self._device_id)

        # enable external control
        await self._modbus.write_register(self.name, 40210, to_u32_list(1079), device_id=self._device_id)

        self.is_controlled = True

    async def relinquish_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to relinquish control, not connected', source=self.name)

        self.is_controlled = False

        await self._modbus.write_register(self.name, 40210, to_u32_list(303), device_id=self._device_id) # disable external setpoint control

        # Parameter.Inverter.WModCfg.WCtlComCfg.Ena, 303 = OFF (potentially needed)
        await self._modbus.write_register(self.name, 41383, to_u32_list(303), device_id=self._device_id)

    async def read_stats(self) -> SolarInverterStats:
        total_pow, l1_pow, l2_pow, l3_pow, setpoint_limit = await self._modbus.read_register_seq(self.name, [
            (30775, 'S32', 'FIX0'), (30777, 'S32', 'FIX0'), (30779, 'S32', 'FIX0'), (30781, 'S32', 'FIX0'), (31405, 'U32', 'FIX0'),
        ], device_id=self._device_id)

        control_status = ControlStatus.DEGRADED if any(
            v is None for v in [total_pow, l1_pow, l2_pow, l3_pow]
        ) else ControlStatus.NOMINAL

        if l1_pow is None or l2_pow is None or l3_pow is None or total_pow is None:
            self.log.error(f'solar inverter: L1={l1_pow} W  L2={l2_pow} W  L3={l3_pow} W  total={total_pow} W')
        else:
            self.log.debug(f'solar inverter: L1={l1_pow:.0f} W  L2={l2_pow:.0f} W  L3={l3_pow:.0f} W  total={total_pow:.0f} W')

        return SolarInverterStats(
            control_status=control_status,
            setpoint_limit_w=setpoint_limit,
            total_power_w=total_pow,
            ac_side={
                Phase.L1: SPCStats(power=l1_pow),
                Phase.L2: SPCStats(power=l2_pow),
                Phase.L3: SPCStats(power=l3_pow),
            },
        )

    async def set_power(self, power_w: float) -> None:
        '''Apply a curtailment setpoint capping total output at `power_w` W across all connected
        phases. `power_w == 0` means full curtailment (a 0 W limit). Relinquishing control (reg 40210=303)
        removes the cap and lets the inverter run freely again.'''
        if power_w < 0:
            raise ProgrammingError('solar inverter can only source power, not sink it', source=self.name)
        elif power_w > 25_000:
            raise ProgrammingError('exceeds power set point for this solar inverter', source=self.name)

        await self._modbus.write_register(self.name, 41251, to_s32_list(int(power_w)), device_id=self._device_id)
