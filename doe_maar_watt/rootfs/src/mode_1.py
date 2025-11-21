import asyncio
from modbus import ModbusManager

async def mode_1_loop():
    print(f'Mode 1 initializing')

    while True:
        print(f'idle mode: connecting modbus client')
        client = ModbusManager()
        await client.connect()

        print(f'idle: relinquish control and set ')
        await client.write_registers(40149, [0, 0])  # rendement
        await client.write_registers(40151, [0, 803])  # 803 = inactive

        client.close()

        await asyncio.sleep(10)
