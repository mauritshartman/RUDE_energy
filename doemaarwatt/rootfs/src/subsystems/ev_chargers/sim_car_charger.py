from typing import Any
from datetime import datetime as dt

from common import Logger, ControlStatus, Phase, SPCStats, ControlException
from .base import BaseEVCharger, EVChargerStats, EVChargingStatus


class SimCarCharger(BaseEVCharger):

    def __init__(self,
        name: str,
        connected_phase: Phase,
        log: Logger,
    ) -> None:
        super().__init__(name, connected_phase, log)

        self.is_connected = False
        self.is_controlled = False

        self.control_status = ControlStatus.UNCONTROLLED
        self.ev_charging_status = EVChargingStatus.NO_CAR_CONNECTED

    @classmethod
    def from_config(cls, cfg: dict[str, Any], log: Logger) -> 'SimCarCharger':
        return cls(
            name=cfg.get('name', 'Simulated EV charger'),
            connected_phase=cfg.get('connected_phase', Phase.ALL),
            log=log,
        )

    @property
    def power_limits_phase(self) -> tuple[float, float]:
        return (
            -22_000 / 3.0, # simuilated charger only sinks power for now
            0.0, # EV charger only sinks power for now
        )

    def get_charging_status(self) -> EVChargingStatus:
        return self.ev_charging_status

    async def connect(self) -> None:
        self.is_connected = True

    def close(self) -> None:
        self.is_controlled = False
        self.is_connected = False

        self.control_status = ControlStatus.UNCONTROLLED

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

    async def read_stats(self) -> EVChargerStats:
        self.control_status = ControlStatus.NOMINAL


        now = dt.now(tz=self.log.tz)
        if now.hour % 2 == 0:
            self.log.info('reading simulated EV charger properties (charging):')
            self.ev_charging_status = EVChargingStatus.CONNECTED_CHARGING
            l1_current = -15.1
            l2_current = -15.2
            l3_current = -15.3
        else:
            self.log.info('reading simulated EV charger properties (idle):')
            self.ev_charging_status = EVChargingStatus.NO_CAR_CONNECTED
            l1_current = 0.0
            l2_current = 0.0
            l3_current = 0.0

        l1_voltage = 231
        l2_voltage = 232
        l3_voltage = 233

        l1_power = l1_voltage * l1_current
        l2_power = l2_voltage * l2_current
        l3_power = l3_voltage * l2_current

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
