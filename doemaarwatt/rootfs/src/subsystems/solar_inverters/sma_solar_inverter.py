from typing import Any

from common import Logger, ModbusManager, to_u32_list, ControlStatus, Phase, SPCStats, ProgrammingError, ControlException
from .base import BaseSolarInverter, SolarInverterStats, SolarGenerationStatus


REG_30201_TAGLIST = {
    35: 'Fault',
    303: 'Off',
    307: 'Ok', # default value
    455: 'Warning',
}
REG_40029_TAGLIST = {
    303: 'Off',
    569: 'Activated', # default value
    1295: 'Standby',
    1795: 'Bolted',
}
REG_30217_TAGLIST = {
    51: 'Closed',
    311: 'Open', # default value
}
REG_33001_TAGLIST = {
    1393: 'Waiting for PV voltage',
    1394: 'Waiting for valid AC grid',
    4570: 'Wait for enable operation',
}


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

        self.control_status = ControlStatus.UNCONTROLLED
        self.solar_status = SolarGenerationStatus.UNKNOWN

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

    def get_solar_status(self) -> SolarGenerationStatus:
        return self.solar_status

    async def connect(self) -> None:
        await self._modbus.connect()
        self.is_connected = True

    def close(self) -> None:
        self.is_controlled = False
        self.is_connected = False

        self.control_status = ControlStatus.UNCONTROLLED
        self.solar_status = SolarGenerationStatus.UNKNOWN

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
        self.control_status = ControlStatus.NOMINAL

    async def relinquish_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to relinquish control, not connected', source=self.name)

        self.is_controlled = False
        self.control_status = ControlStatus.DEGRADED
        self.solar_status = SolarGenerationStatus.UNKNOWN

        # WMod = 303 (Off): stop the active-power preset so the inverter runs unlimited again
        await self._modbus.write_register(self.name, 40210, to_u32_list(303), device_id=self._device_id)

        # keep the external-communication channel off as well (defensive; it is not used in the manual scheme)
        await self._modbus.write_register(self.name, 41383, to_u32_list(303), device_id=self._device_id)

    async def _determine_status(self) -> None:
        '''Query the inverter to check whether it is capable of generating solar power. The following checks are made:
        - Overall condition (register 30201) -> should read '307 ok'
        - General operating status (register 40029) -> should read '569 activated' or '1295 degraded'
        - Grid contactor open/closed (register 30217) -> shoudl read '51 closed' or '311 open'

        Based on these, self.solar_status is updated
        '''
        overall_cond = await self._modbus.read_register(self.name, 30201, 'U32', device_id=self._device_id, sma_format=REG_30201_TAGLIST)
        if overall_cond is None or overall_cond != 'Ok': # Fault / Off / Warning
            self.log.error(f'solar inverter {self.name}: overall condition not OK: {overall_cond}')
            self.control_status = ControlStatus.DEGRADED
            self.solar_status = SolarGenerationStatus.UNKNOWN
            return

        # overall condition is Ok, so continue checking status:

        # check contactor status
        grid_contactor = await self._modbus.read_register(self.name, 30217, 'U32', device_id=self._device_id, sma_format=REG_30217_TAGLIST)
        if grid_contactor is None:
            self.log.error(f'solar inverter {self.name}: unable to determine grid contactor status')
            self.control_status = ControlStatus.DEGRADED
            self.solar_status = SolarGenerationStatus.UNKNOWN
            return

        # check general operating status
        gen_op_status = await self._modbus.read_register(self.name, 30201, 'U32-STATUS', device_id=self._device_id, sma_format=REG_40029_TAGLIST)
        if gen_op_status is None or gen_op_status == 'Off' or gen_op_status == 'Bolted':
            gen_op_status_str = 'information not available' if gen_op_status is None else gen_op_status
            self.log.error(f'solar inverter {self.name}: general operating status not nominal: {gen_op_status_str}')
            self.control_status = ControlStatus.DEGRADED
            self.solar_status = SolarGenerationStatus.UNKNOWN
            return

        # nominal #1: sun is shing and we are supplying power to the AC side:
        if grid_contactor == 'Closed' and gen_op_status == 'Activated':
            self.log.info(f'solar inverter {self.name}: grid contactor closed and inverter activated')
            self.control_status = ControlStatus.NOMINAL
            self.solar_status = SolarGenerationStatus.GENERATING
            return

        # nominal #2: sun is not shining
        if gen_op_status == 'Standby':
            # as an extra: check the standby status (register 33001)
            standby_status = await self._modbus.read_register(self.name, 33001, 'U32-STATUS', device_id=self._device_id, sma_format=REG_33001_TAGLIST)
            self.log.info(f'solar inverter {self.name}: in standby ({standby_status})')
            self.control_status = ControlStatus.NOMINAL
            self.solar_status = SolarGenerationStatus.STANDBY
            return

        raise ProgrammingError(f'solar inverter unable to properly determine status', source=self.name)

    async def read_stats(self) -> SolarInverterStats:
        # first determine the solar status
        await self._determine_status() # self.control_status and self.solar_status are now updated

        # nominal operation and sun is shining:
        if self.control_status == ControlStatus.NOMINAL and self.solar_status == SolarGenerationStatus.GENERATING:
            # setpoint is read back from WCnstCfg.W (30837) - the same manual active-power preset set_power() writes
            total_pow, l1_pow, l2_pow, l3_pow, setpoint_limit = await self._modbus.read_register_seq(self.name, [
                (30775, 'S32', 'FIX0'), (30777, 'S32', 'FIX0'), (30779, 'S32', 'FIX0'), (30781, 'S32', 'FIX0'), (30837, 'U32', 'FIX0'),
            ], device_id=self._device_id)

            if l1_pow is None or l2_pow is None or l3_pow is None or total_pow is None:
                self.control_status = ControlStatus.DEGRADED
                self.log.error(f'solar inverter {self.name}: degraded status L1={l1_pow} W  L2={l2_pow} W  L3={l3_pow} W  total={total_pow} W')
            else:
                self.control_status = ControlStatus.NOMINAL
                self.log.debug(f'solar inverter {self.name}: L1={l1_pow:.0f} W  L2={l2_pow:.0f} W  L3={l3_pow:.0f} W  total={total_pow:.0f} W')

            return SolarInverterStats(
                control_status=self.control_status,
                solar_status=self.solar_status,
                setpoint_limit_w=setpoint_limit,
                total_power_w=total_pow,
                ac_side={
                    Phase.L1: SPCStats(power=l1_pow),
                    Phase.L2: SPCStats(power=l2_pow),
                    Phase.L3: SPCStats(power=l3_pow),
                },
            )

        # degraded operation and/or sun is not shining:
        return SolarInverterStats(
            control_status=self.control_status,
            solar_status=self.solar_status,
            setpoint_limit_w=0,
            total_power_w=0,
            ac_side={
                Phase.L1: SPCStats(power=0),
                Phase.L2: SPCStats(power=0),
                Phase.L3: SPCStats(power=0),
            },
        )

    async def set_power(self, power_w: float) -> None:
        '''Apply an active-power limit capping total output at `power_w` W across all connected phases.
        `power_w == 0` means full curtailment (a 0 W limit). The value is written to the manual active-power
        preset register WCnstCfg.W (40212); relinquishing control (WMod 40210=303) removes the limit and lets
        the inverter run freely again.'''

        if self.solar_status != SolarGenerationStatus.GENERATING:
            self.log.error(f'solar inverter {self.name} has solar status {self.solar_status}: commanding a power limit {power_w} does not make sense')
            return

        if power_w < 0:
            raise ProgrammingError('solar inverter can only source power, not sink it', source=self.name)
        elif power_w > 25_000:
            raise ProgrammingError('exceeds power set point for this solar inverter', source=self.name)

        await self._modbus.write_register(self.name, 40212, to_u32_list(int(power_w)), device_id=self._device_id)
