from abc import ABC, abstractmethod

from .logger import Logger
from .definitions import Phase
from .exceptions import DMWException


class ControlException(DMWException):
    def __init__(self, message: str, source: str, requires_fallback: bool = False) -> None:
        super().__init__(message, source, requires_fallback)


class BaseInverter(ABC):

    def __init__(self, name: str, connected_phase: Phase, log: Logger) -> None:
        self.name = name
        self.connected_phase = Phase(connected_phase)
        self.log = log

    @abstractmethod
    async def connect(self) -> None:
        '''Establish a connection (typically over Modbus) to an inverter
        '''
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        '''Close the connection (typically Modbus) to an inverter
        '''
        raise NotImplementedError

    @abstractmethod
    async def enable_control(self) -> None:
        '''Put the inverter in a state where it can be directly controlled by this application.
        '''
        raise NotImplementedError

    @abstractmethod
    async def relinquish_control(self) -> None:
        '''Put the inverter in a state where it is no longer directly controlled by this application.
        '''
        raise NotImplementedError

    @abstractmethod
    async def set_power(self, power_w: float) -> None:
        '''Command a desired power level to the inverter. The power level is the same across all three phases.
        '''
        raise NotImplementedError

    @property
    @abstractmethod
    def power_limits_phase(self) -> tuple[float, float]:
        '''Lower (charge / consumed power) and upper (discharge / produced power) limits for the inverter, expressed in Watts.
        Commanded power must be within this range. Applies separately to each phase the inverter is connected to.
        '''
        raise NotImplementedError

    def apply_power_limits(self, power_w: float) -> float:
        low, high = self.power_limits_phase
        if low <= power_w and power_w <= high: # within range, so return verbatim
            return power_w

        if power_w < low: # too low, so clamp to low limit
            return low

        return high # third case: must be too high
