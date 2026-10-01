from typing import Any

from prettytable import PrettyTable

from common import Logger, ModbusManager, ControlStatus, Phase, SPCStats, ControlException
from .base import BaseEVCharger, EVChargerStats, EVChargingStatus


# Modbus server addresses (configuration guide, section 4.1): the charging station as a whole is reached at
# 200, the socket related registers (the measurements, and the Mode 3 state) at 1, or at 2 for the right
# socket of a dual socket station. This driver is meant for a single socket 3-phase Alfen Eve Pro charger,
# so only 1 applies.
STATION_DEVICE_ID = 200
SOCKET_DEVICE_ID = 1

EXPECTED_MANUFACTURER = 'Alfen B.V.'  # what registers 117..121 read on every Alfen charging station


class AlfenEvePro(BaseEVCharger):

    def __init__(self,
        name: str,
        connected_phase: Phase,
        host: str,
        port: int,
        log: Logger,
    ) -> None:
        super().__init__(name, connected_phase, log)

        self._modbus = ModbusManager(
            client_configs=[{'name': name, 'host': host, 'port': port, 'enable': True}],
            log=log,
        )

        self.is_connected = False
        self.is_controlled = False

        self.control_status = ControlStatus.UNCONTROLLED
        self.ev_charging_status = EVChargingStatus.NO_CAR_CONNECTED

    @classmethod
    def from_config(cls, cfg: dict[str, Any], log: Logger) -> 'AlfenEvePro':
        return cls(
            name=cfg.get('name', 'Alfen Eve Pro'),
            connected_phase=cfg.get('connected_phase', Phase.ALL),
            host=cfg['host'],
            port=cfg.get('port', 502),
            log=log,
        )

    @property
    def power_limits_phase(self) -> tuple[float, float]:
        return (
            -22_000 / 3.0, # EV charger only sinks power for now
            0.0, # EV charger only sinks power for now
        )

    def get_charging_status(self) -> EVChargingStatus:
        return self.ev_charging_status

    async def connect(self) -> None:
        await self._modbus.connect()
        self.is_connected = True

    def close(self) -> None:
        self.is_controlled = False
        self.is_connected = False

        self.control_status = ControlStatus.UNCONTROLLED

        self._modbus.close()

    async def enable_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to assert control, not connected', source=self.name)

        # For now we do not take active control of the Alfen charger. We only read stats from it in order to
        # maintain safe power levels for the main fuse.

        self.is_controlled = True
        self.control_status = ControlStatus.NOMINAL

    async def relinquish_control(self) -> None:
        if not self.is_connected:
            raise ControlException(f'unable to relinquish control, not connected', source=self.name)

        self.is_controlled = False
        self.control_status = ControlStatus.UNCONTROLLED

    async def set_power(self, power_w: float) -> None:
        '''For now, we only use EV chargers in read-only mode: only gather stats from them in order to
        know when they are charging in order to protect the main fuse and/or use excessive solar production
        to charge the EV.

        So this is a NOP for now'''
        pass

    async def _read(self,
        register: int,
        dtype: str,
        device_id: int = SOCKET_DEVICE_ID,
        word_count: int = 0,
    ) -> Any:
        '''Read a register by the number the Alfen documentation gives it, which is also the Modbus address to
        ask for. The configuration guide (section 3.4) claims otherwise - 'Register 1 has an offset from 0
        [...] Always subtract 1 from the register value to get the Modbus address' - but the charging station
        does not do this, as reading it both ways shows:
            - register 117 (manufacturer) read at 116 returns the zero padding at the end of the name field
              that precedes it (registers 100..116), so the string comes back empty. Read at 117 it returns
              'Alfen B.V.' (see EXPECTED_MANUFACTURER, which is checked on every read_stats)
            - register 1200 (availability) read at 1199 is refused with 'Illegal Data Address', 1199 being
              part of the gap between the station registers (up to 1105) and the status registers (from 1200)
        Every Alfen register is a holding register, which the address itself does not tell (the socket
        measurements start with a 3, the rest with a 1), so reading them is always forced to Modbus function
        0x03.

        A STRING spans as many registers as the documentation lists for it, which has to be passed as
        word_count. The station registers are read with STATION_DEVICE_ID, the socket ones (the default) with
        SOCKET_DEVICE_ID.
        '''
        return await self._modbus.read_register(
            self.name, register, dtype,
            device_id=device_id,
            force_holding_register=True,
            word_count=word_count,
        )

    async def read_stats(self) -> EVChargerStats:
        self.log.debug('reading EV charger properties:')

        # safety check for STRING datatype: read register 117-121 (manufacturer) which should yield 'Alfen B.V.'
        manufacturer = await self._read(117, 'STRING', device_id=STATION_DEVICE_ID, word_count=5)
        if manufacturer != EXPECTED_MANUFACTURER:
            self.log.error(f'{self.name}: expected the manufacturer register to read {EXPECTED_MANUFACTURER!r}, '
                           f'but it reads {manufacturer!r}: check the Modbus server address and the decoding '
                           f'of strings and register addresses before trusting any other reading')
        else:
            self.log.debug(f'{self.name}: manufacturer register reads {manufacturer!r} as expected')

        availability = await self._read(1200, 'U16', SOCKET_DEVICE_ID) # 1 operative, 0 inoperative
        mode_3_state = await self._read(1201, 'STRING', SOCKET_DEVICE_ID, word_count=5) # IEC 61851 mode 3 status
        # TODO: set the ev_charging_status based on availability and mode 3 status
        self.log.info(f'{self.name}: availability {availability}, mode 3 status: {mode_3_state}')

        l1_voltage = await self._read(306, 'FLOAT32', SOCKET_DEVICE_ID) # L1-N voltage
        l2_voltage = await self._read(308, 'FLOAT32', SOCKET_DEVICE_ID) # L2-N voltage
        l3_voltage = await self._read(310, 'FLOAT32', SOCKET_DEVICE_ID) # L3-N voltage

        l1_current = await self._read(320, 'FLOAT32', SOCKET_DEVICE_ID) # L1 current
        l2_current = await self._read(322, 'FLOAT32', SOCKET_DEVICE_ID) # L2 current
        l3_current = await self._read(324, 'FLOAT32', SOCKET_DEVICE_ID) # L3 current

        l1_power = await self._read(338, 'FLOAT32', SOCKET_DEVICE_ID) # L1 real power
        l2_power = await self._read(340, 'FLOAT32', SOCKET_DEVICE_ID) # L2 real power
        l3_power = await self._read(342, 'FLOAT32', SOCKET_DEVICE_ID) # L3 real power

        unreadable = [name for name, value in (
            ('availability (1200)', availability), ('mode 3 state (1201)', mode_3_state),
            ('L1 voltage (306)', l1_voltage), ('L2 voltage (308)', l2_voltage), ('L3 voltage (310)', l3_voltage),
            ('L1 current (320)', l1_current), ('L2 current (322)', l2_current), ('L3 current (324)', l3_current),
            ('L1 power (338)', l1_power), ('L2 power (340)', l2_power), ('L3 power (342)', l3_power),
        ) if value is None]
        if unreadable:
            self.control_status = ControlStatus.DEGRADED
            self.log.error(f'{self.name}: error reading stats, no value for {", ".join(unreadable)}')

            return EVChargerStats(
                control_status=self.control_status,
                ev_charging_status=self.ev_charging_status,
                total_power_w=None,
                ac_side={
                    Phase.L1: SPCStats(),
                    Phase.L2: SPCStats(),
                    Phase.L3: SPCStats(),
                },
            )

        self.control_status = ControlStatus.NOMINAL

        # An EV charger only consumes power (for now), so ensure proper signing convention for current and power:
        l1_current = -1 * abs(l1_current)
        l2_current = -1 * abs(l2_current)
        l3_current = -1 * abs(l3_current)
        l1_power = -1 * abs(l1_power)
        l2_power = -1 * abs(l2_power)
        l3_power = -1 * abs(l3_power)

        ret = EVChargerStats(
            control_status=self.control_status,
            ev_charging_status=self.ev_charging_status,
            total_power_w=l1_power + l2_power + l3_power,
            ac_side={
                Phase.L1: SPCStats(current=l1_current, voltage=l1_voltage, power=l1_power),
                Phase.L2: SPCStats(current=l2_current, voltage=l2_voltage, power=l2_power),
                Phase.L3: SPCStats(current=l3_current, voltage=l3_voltage, power=l3_power),
            },
        )

        self.log.info(f'{self.name}: read stats:\n{ret.to_dict()}')
        return ret
