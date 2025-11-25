import asyncio
from modbus import ModbusManager

async def mode_1_loop():
    print(f'Mode 1 initializing')

    while True:
        try:
            print(f'idle mode: connecting modbus client')
            client = ModbusManager()
            await client.connect()

            print(f'idle: relinquish control and reset power set point')
            await client.write_registers(40149, [0, 0])  # reset rendement
            await client.write_registers(40151, [0, 803])  # 803 = inactive

            print(f'idle: reading selected inverter properties:')
            temps = await client.read_registers(30849, 'S32', device_id=3, sma_data_format='TEMP')
            print(f'\tbattery temperatures:')
            for inv_name, temp in temps.items():
                print(f'\t\t{inv_name}:\t{temp} {chr(176)}C')

        except Exception as e:
            print(f'idle: encountered an error: {e}')

        finally:
            client.close()

        await asyncio.sleep(10)
