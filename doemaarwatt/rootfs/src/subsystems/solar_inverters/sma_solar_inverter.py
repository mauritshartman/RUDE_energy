import math
from typing import Any, Optional

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
    302: 'Undocumented 33001 response',  # not listed for this register, but what the hardware answers with while in standby
    1393: 'Waiting for PV voltage',
    1394: 'Waiting for valid AC grid',
    4570: 'Wait for enable operation', # default value
}


N_PHASES = 3  # this inverter is three phase, as the constructor asserts

# Fallback for WMax, which is read from the inverter on connect. Only used when that read fails
PEAK_POWER_W = 25_000
PEAK_POWER_W_PHASE = PEAK_POWER_W // N_PHASES

# Active power limitation over the 'External active power setpoint' channel (WModCfg.WCtlComCfg). The limit
# itself is a percentage of WMax written to 40016, which the parameter list marks as a Device Control Object
# and so is meant to be written cyclically - unlike the manual-preset registers (40212 / 40214), which are
# flash-stored parameters carrying the list's 'warning against cyclical writing'.
REG_WMOD = 40210          # Parameter.Inverter.WModCfg.WMod - operating mode of the active power setting
REG_WCTLCOM_ENA = 41383   # Parameter.Inverter.WModCfg.WCtlComCfg.Ena - external setpoint channel on/off
REG_WNOM_PCT = 40016      # Setpoint..WModCfg.WCtlComCfg.WNom - S16 / FIX0, 0 .. 100 % of WMax, write-only
REG_WMAX = 30233          # Parameter.Inverter.WMax - the 'set active power limit' the percentage is of

WMOD_OFF = 303
WMOD_EXTERNAL_SETPOINT = 1079  # follow the WNom percentage written over the external setpoint channel
ENA_OFF = 303
ENA_ON = 308

NO_LIMIT_PCT = 100  # a setpoint of 100 % of WMax is the inverter's full range, i.e. no limitation


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

        self.setpoint_limit: Optional[float] = None

        # WMax, read from the inverter on connect: the reference the normalized setpoint is a percentage of
        self._wmax_w: Optional[int] = None

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
            PEAK_POWER_W / 3.0,
        )

    def get_solar_status(self) -> SolarGenerationStatus:
        return self.solar_status

    async def connect(self) -> None:
        await self._modbus.connect()
        self.is_connected = True
        self.setpoint_limit = None
        self._wmax_w = await self._read_wmax()

    async def _read_wmax(self) -> int:
        '''Read WMax, the active power limit that the normalized setpoint of REG_WNOM_PCT is a percentage
        of. Read from the inverter rather than assumed, because it is itself a configurable limit and may
        well sit below what the hardware could deliver (a grid code cap, say). A percentage taken against
        the wrong reference quietly commands the wrong number of Watts, with nothing to read back that
        would show it: the setpoint register is write-only.
        '''
        wmax = await self._modbus.read_register(self.name, REG_WMAX, 'U32', device_id=self._device_id,
                                                sma_format='FIX0')
        if wmax is None or wmax <= 0:
            self.log.error(f'{self.name}: unable to read WMax ({REG_WMAX}), got {wmax}: falling back to '
                           f'{PEAK_POWER_W} W as the reference for the normalized power setpoint')
            return PEAK_POWER_W

        self.log.info(f'{self.name}: WMax is {wmax:.0f} W, so one percent of the normalized power '
                      f'setpoint is {wmax / 100:.0f} W')
        return int(wmax)

    def close(self) -> None:
        self.is_controlled = False
        self.is_connected = False
        self.setpoint_limit = None

        self.control_status = ControlStatus.UNCONTROLLED
        self.solar_status = SolarGenerationStatus.UNKNOWN

        self._modbus.close()

    def has_live_connection(self) -> bool:
        # deliberately not self.is_connected: that only records that connect() was once called and says
        # nothing about whether the transport underneath is still there
        return self._modbus.connected

    async def _ensure_parameter(self, address: int, value: int, description: str) -> None:
        '''Write one of the flash-stored mode parameters, but only when it does not already hold `value`.

        The parameter list marks these with a warning against writing them cyclically, and both
        enable_control and relinquish_control are called on every control loop iteration. Writing them
        unconditionally would be thousands of writes a day to non-volatile memory for a value that changes
        twice a day at most. Reading first costs one request and makes the write happen only on a change.
        '''
        current = await self._modbus.read_register(self.name, address, 'U32', device_id=self._device_id)
        if current == value:
            return

        self.log.info(f'{self.name}: setting {description} ({address}) from {current} to {value}')
        await self._modbus.write_register(self.name, address, to_u32_list(value), device_id=self._device_id)

    async def enable_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to assert control, not connected', source=self.name)

        # Use the external active power setpoint channel: WMod (40210) = 1079, with the channel itself
        # enabled (41383 = On, which is not its default). The limit is then a percentage of WMax written to
        # WCtlComCfg.WNom (40016). This replaces the manual preset in Watts (WMod = 1077, setpoint in
        # WCnstCfg.W 40212), whose setpoint register is a flash-stored parameter and so cannot be written
        # once per control loop the way a limit that tracks the main fuse has to be.
        # Register settings controlled elsewhere
        # await self._ensure_parameter(REG_WCTLCOM_ENA, ENA_ON, 'external active power setpoint channel')
        # await self._ensure_parameter(REG_WMOD, WMOD_EXTERNAL_SETPOINT, 'active power operating mode')

        self.is_controlled = True
        self.control_status = ControlStatus.NOMINAL

    async def relinquish_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to relinquish control, not connected', source=self.name)

        self.is_controlled = False
        self.control_status = ControlStatus.DEGRADED
        self.solar_status = SolarGenerationStatus.UNKNOWN

        # Hand the full range back before switching the channel off, so the inverter is left running freely
        # rather than holding whatever percentage was commanded last
        # await self._modbus.write_register(self.name, REG_WNOM_PCT, [NO_LIMIT_PCT], device_id=self._device_id)

        # await self._ensure_parameter(REG_WMOD, WMOD_OFF, 'active power operating mode')
        # await self._ensure_parameter(REG_WCTLCOM_ENA, ENA_OFF, 'external active power setpoint channel')

        self.setpoint_limit = None

    async def _determine_status(self) -> None:
        '''Query the inverter to check whether it is capable of generating solar power. The following checks are made:
        - Overall condition (register 30201) -> should read '307 ok'
        - General operating status (register 40029) -> should read '569 activated' or '1295 degraded'
        - Grid contactor open/closed (register 30217) -> shoudl read '51 closed' or '311 open'

        Based on these, self.solar_status is updated
        '''
        # The condition and the contactor lie 16 registers apart, so one request of 18 fetches both. Reading
        # the contactor before knowing the condition is Ok costs nothing - it is the round trip that costs,
        # and this runs on every control loop iteration. The operating status below stays a request of its
        # own: it is a holding register, which can never share a request with these two input registers
        overall_cond, grid_contactor = await self._modbus.read_register_batch(self.name, [
            (30201, 'U32', REG_30201_TAGLIST),  # overall condition
            (30217, 'U32', REG_30217_TAGLIST),  # grid relay / contactor
        ], device_id=self._device_id)

        if overall_cond is None or overall_cond != 'Ok': # Fault / Off / Warning
            self.log.error(f'solar inverter {self.name}: overall condition not OK: {overall_cond}')
            self.control_status = ControlStatus.DEGRADED
            self.solar_status = SolarGenerationStatus.UNKNOWN
            return

        # overall condition is Ok, so continue checking status:

        # check contactor status
        if grid_contactor is None:
            self.log.error(f'solar inverter {self.name}: unable to determine grid contactor status')
            self.control_status = ControlStatus.DEGRADED
            self.solar_status = SolarGenerationStatus.UNKNOWN
            return

        # check general operating status
        gen_op_status = await self._modbus.read_register(self.name, 40029, 'U32-STATUS', device_id=self._device_id, sma_format=REG_40029_TAGLIST)
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
            # The four power values sit back to back in 30775..30782, so one request of 8 registers fetches
            # all of them where four used to be needed.
            # No read-back of the limit: every WCtlComCfg register is write-only, and 30837 - which the
            # previous scheme read - mirrors WCnstCfg.W, the manual preset, which nothing writes any more.
            # What was commanded is held in self.setpoint_limit; whether it binds shows in the power read here
            total_pow, l1_pow, l2_pow, l3_pow = await self._modbus.read_register_batch(self.name, [
                (30775, 'S32', 'FIX0'), (30777, 'S32', 'FIX0'), (30779, 'S32', 'FIX0'), (30781, 'S32', 'FIX0'),
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
                # a total, which is what this field is elsewhere, where get_setpoint_limit() is per phase
                setpoint_limit_w=None if self.setpoint_limit is None else self.setpoint_limit * N_PHASES,
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

    def get_control_status(self) -> ControlStatus:
        return self.control_status

    def get_setpoint_limit(self) -> float | None:
        return self.setpoint_limit

    async def set_power_limit(self, power_w: Optional[float]) -> None:
        '''Cap total active power output at `power_w` W across all connected phases. `power_w == 0` means
        full curtailment, None removes the limit and hands the inverter its full range back.

        `power_w` is the total, not a per-phase figure: that is what BaseController.command_PBSsent passes
        (it multiplies the per-phase limit by the number of phases first). Watts is the unit the rest of
        the application reasons in; converting to the percentage of WMax that REG_WNOM_PCT wants is this
        driver's business.

        Mind the resolution that percentage brings: REG_WNOM_PCT is FIX0 over a range of 0 .. 100, so one
        step is a whole percent of WMax - 250 W where WMax is 25 kW. The limit is rounded down to the next
        whole percent, so the figure asked for is never overshot, and what the inverter was actually told
        is what gets recorded for the safety checks to reason about.
        '''
        if power_w is None:
            self.setpoint_limit = None
            # without this the inverter holds the last percentage commanded, so releasing the limit in the
            # controller would not actually release it on the inverter
            if self.is_controlled:
                await self._modbus.write_register(self.name, REG_WNOM_PCT, [NO_LIMIT_PCT],
                                                  device_id=self._device_id)
            return

        if self.solar_status != SolarGenerationStatus.GENERATING:
            self.log.error(f'solar inverter {self.name} has solar status {self.solar_status}: commanding for a power limit {power_w} is being ignored')
            return

        power_w = int(power_w)
        if power_w < 0:
            raise ProgrammingError('solar inverter can only source power, not sink it', source=self.name)
        elif power_w > PEAK_POWER_W:
            raise ProgrammingError(f'power limit of {power_w} W exceeds the peak power of this solar '
                                   f'inverter ({PEAK_POWER_W} W)', source=self.name)

        wmax = self._wmax_w or PEAK_POWER_W
        pct = min(NO_LIMIT_PCT, max(0, math.floor(power_w * 100 / wmax)))

        await self._modbus.write_register(self.name, REG_WNOM_PCT, [pct], device_id=self._device_id)

        # Record what the inverter was told, not what was asked for, and per phase: that is the contract
        # get_setpoint_limit has with its callers (see MainFuseProtectionMixin)
        effective_total_w = pct * wmax / 100.0
        self.setpoint_limit = effective_total_w / N_PHASES
        self.log.debug(f'{self.name}: power limit {power_w} W of {wmax} W WMax -> {pct} % '
                       f'(= {effective_total_w:.0f} W total, {self.setpoint_limit:.0f} W per phase)')

    def is_curtailed(self) -> bool:
        return not self.setpoint_limit is None
