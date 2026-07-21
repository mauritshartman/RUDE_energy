from enum import StrEnum
from dataclasses import dataclass
from typing import Optional


class Phase(StrEnum):
    L1 = 'L1'
    L2 = 'L2'
    L3 = 'L3'
    ALL = 'ALL'

    @property
    def is_single_phase(self) -> bool:
        return self != Phase.ALL


SINGLE_PHASES = [ Phase.L1, Phase.L2, Phase.L3 ]


@dataclass
class SPCStats:
    '''
    SPCStats (SubsystemPhaseConnectionStats) captures key metrics measured at the connection point of a subsystem
    for a single phase. Note that some subsystems can be connected to a single phase (SMA Sunny Boy Storage), while others are
    connected to all three phases (SMA TriPower).

    The voltages have a zero or positive value.
    Currents and power can be both negative or positive. Negative means the subsystem is sinking current or power,
    while positive means it is sourcing.
    '''
    current: Optional[float] = None
    voltage: Optional[float] = None
    power: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'A': self.current,
            'V': self.voltage,
            'P': self.power,
        }

    def status(self) -> str:
        if self.power is None:
            return 'disconnected / unknown'
        elif self.power == 0:
            return 'no power'
        elif self.power < 0:
            return 'consuming power'
        else:
            return 'producing power'


class ControlStatus(StrEnum):
    UNCONTROLLED = 'UNCONTROLLED' # subsystem is currently not being controlled
    NOMINAL = 'NOMINAL' # subsystem is fully controlled
    DEGRADED = 'DEGRADED' # subsystem is only partially being controlled: only some registers could be read/written and/or a NaN value is returned
