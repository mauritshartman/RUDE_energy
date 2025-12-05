import asyncio
import time
from modbus import ModbusManager
from config import config, ControlMode
from mode_1 import mode_1_loop
from mode_2 import mode_2_loop


async def main():
    mode = config.get_control_mode()
    print(f'DoeMaarWatt addon started up in {mode.name} control mode')

    if mode == ControlMode.NONE:
        await mode_1_loop()
    elif mode == ControlMode.MANUAL:
        await mode_2_loop()
    else:
        raise Exception(f'controle mode {mode.name} not implemented')


if __name__ == "__main__":
    asyncio.run(main())
