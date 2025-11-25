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

            print(f'\tbattery temperatures [min/average/max]:')
            temps_high = await client.read_registers(32221, 'S32', device_id=3, sma_data_format='TEMP')
            temps_low  = await client.read_registers(32227, 'S32', device_id=3, sma_data_format='TEMP')
            for inv_name in temps_high.keys() & temps_low.keys():
                temp_h = temps_high[inv_name]
                temp_l = temps_low[inv_name]
                temp_a = (temp_l + temp_h) / 2
                print(f'\t\t{inv_name}:\t{temp_l} {chr(176)}C\t{temp_a} {chr(176)}C\t{temp_h} {chr(176)}C')

            print(f'\tbattery charge percentage:')
            charges = await client.read_registers(32233, 'U32', device_id=3, sma_data_format='FIX2')
            for inv_name, charge in charges.items():
                print(f'\t\t{inv_name}:\t{charge:.2f} %')

            print(f'\tbattery voltage:')
            voltages = await client.read_registers(30851, 'U32', device_id=3, sma_data_format='FIX2')
            for inv_name, voltage in voltages.items():
                print(f'\t\t{inv_name}:\t{voltage:.2f} V')

            print(f'\tbattery current:')
            currents = await client.read_registers(30843, 'S32', device_id=3, sma_data_format='FIX3')
            for inv_name, current in currents.items():
                print(f'\t\t{inv_name}:\t{current:.3f} A')

        except Exception as e:
            print(f'idle: encountered an error: {e}')

        finally:
            client.close()

        await asyncio.sleep(10)
