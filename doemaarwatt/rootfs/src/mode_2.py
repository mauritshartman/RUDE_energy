import asyncio
from modbus import ModbusManager
from config import config

async def mode_2_loop():
    print(f'Mode 2 (manual charge) initializing')

    while True:
        print(f'manual charge mode: connecting modbus client')
        client = ModbusManager()
        await client.connect()

        charge_amount = config.get_charge_amount()
        print(f'manual charging: assume control and charge batteries at {charge_amount / 1e3:.1f} kW')
        await client.write_registers(40151, [0, 802])  # 802 = active
        await client.write_registers(40149, [65535, 65535 - charge_amount])  # rendement (2s complement?)

        client.close()

        await asyncio.sleep(10)
