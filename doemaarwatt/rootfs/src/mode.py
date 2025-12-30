from enum import IntEnum


class ControlMode(IntEnum):
    IDLE = 1  # idle, connecting to SMA devices and reading values
    MANUAL = 2  # continuous manual charging / discharging
    STATIC = 3  # automatic charging / discharging according to fixed schedule
    DYNAMIC = 4  # automatic charging / discharging according to a dynamic schedule


MIN_MODE_VALUE = min(m.value for m in ControlMode)
MAX_MODE_VALUE = max(m.value for m in ControlMode)
