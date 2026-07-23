from typing import Any

from common import Logger, ModbusManager, to_u32_list, ControlStatus, Phase, SPCStats, ProgrammingError, ControlException
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

        # Use the "manual active-power preset in Watts" scheme: WMod (40210) = 1077. The setpoint is then a W
        # value written to WCnstCfg.W (40212) and read back from 30837 (all in W). This replaces the previous
        # "External setting" (1079) approach, which expects a normalized-% setpoint over the WCtlComCfg channel
        # and left the W read-back (31405) at NaN ('not set' in the UI).
        # First make sure the external-communication setpoint channel is off so only the manual preset is active.
        await self._modbus.write_register(self.name, 41383, to_u32_list(303), device_id=self._device_id)  # WCtlComCfg.Ena = Off
        await self._modbus.write_register(self.name, 40210, to_u32_list(1077), device_id=self._device_id)  # WMod = manual W preset

        self.is_controlled = True

    async def relinquish_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to relinquish control, not connected', source=self.name)

        self.is_controlled = False

        # WMod = 303 (Off): stop the active-power preset so the inverter runs unlimited again
        await self._modbus.write_register(self.name, 40210, to_u32_list(303), device_id=self._device_id)

        # keep the external-communication channel off as well (defensive; it is not used in the manual scheme)
        await self._modbus.write_register(self.name, 41383, to_u32_list(303), device_id=self._device_id)

    async def read_stats(self) -> SolarInverterStats:
        # setpoint is read back from WCnstCfg.W (30837) - the same manual active-power preset set_power() writes
        total_pow, l1_pow, l2_pow, l3_pow, setpoint_limit = await self._modbus.read_register_seq(self.name, [
            (30775, 'S32', 'FIX0'), (30777, 'S32', 'FIX0'), (30779, 'S32', 'FIX0'), (30781, 'S32', 'FIX0'), (30837, 'U32', 'FIX0'),
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
        '''Apply an active-power limit capping total output at `power_w` W across all connected phases.
        `power_w == 0` means full curtailment (a 0 W limit). The value is written to the manual active-power
        preset register WCnstCfg.W (40212); relinquishing control (WMod 40210=303) removes the limit and lets
        the inverter run freely again.'''
        if power_w < 0:
            raise ProgrammingError('solar inverter can only source power, not sink it', source=self.name)
        elif power_w > 25_000:
            raise ProgrammingError('exceeds power set point for this solar inverter', source=self.name)

        await self._modbus.write_register(self.name, 40212, to_u32_list(int(power_w)), device_id=self._device_id)
