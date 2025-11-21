import asyncio
from modbus import ModbusManager
from config import config

async def mode_3_loop():
    print(f'Mode 3 (manual discharge) initializing')

    while True:
        print(f'manual discharge mode: connecting modbus client')
        client = ModbusManager()
        await client.connect()

        discharge_amount = config.get_discharge_amount()
        print(f'manual discharging: assume control and discharge batteries at {discharge_amount / 1e3:.1f} kW')
        await client.write_registers(40151, [0, 802])  # 802 = active
        await client.write_registers(40149, [0, discharge_amount])  # rendement (2s complement?)

        client.close()

        await asyncio.sleep(10)
