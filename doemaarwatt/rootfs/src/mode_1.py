import asyncio
from modbus import ModbusManager
from config import config

DM = 'Data Manager'

async def battery_stats(inverters: ModbusManager):
    print(f'idle: reading selected inverter properties:')

    print(f'\tbattery temperatures [min/average/max]:')
    temps_high = await inverters.read_registers(32221, 'S32', device_id=3, sma_data_format='TEMP')
    temps_low  = await inverters.read_registers(32227, 'S32', device_id=3, sma_data_format='TEMP')
    for inv_name in temps_high.keys() & temps_low.keys():
        temp_h = temps_high[inv_name]
        temp_l = temps_low[inv_name]
        temp_a = (temp_l + temp_h) / 2
        print(f'\t\t{inv_name}:\t{temp_l} {chr(176)}C\t{temp_a} {chr(176)}C\t{temp_h} {chr(176)}C')

    print(f'\tbattery charge percentage:')
    charges = await inverters.read_registers(32233, 'U32', device_id=3, sma_data_format='FIX2')
    for inv_name, charge in charges.items():
        print(f'\t\t{inv_name}:\t{charge:.2f} %')

    print(f'\tbattery voltage:')
    voltages = await inverters.read_registers(30851, 'U32', device_id=3, sma_data_format='FIX2')
    for inv_name, voltage in voltages.items():
        print(f'\t\t{inv_name}:\t{voltage:.2f} V')

    print(f'\tbattery current:')
    currents = await inverters.read_registers(30843, 'S32', device_id=3, sma_data_format='FIX3')
    for inv_name, current in currents.items():
        print(f'\t\t{inv_name}:\t{current:.3f} A')


async def data_manager_stats(dm: ModbusManager):
    print(f'idle: reading data manager properties:')
    l1_voltage = await dm.read_register_client(DM, 31529, 'U32', device_id=2, sma_data_format='FIX2')
    l2_voltage = await dm.read_register_client(DM, 31531, 'U32', device_id=2, sma_data_format='FIX2')
    l3_voltage = await dm.read_register_client(DM, 31533, 'U32', device_id=2, sma_data_format='FIX2')
    l1_current = await dm.read_register_client(DM, 31535, 'S32', device_id=2, sma_data_format='FIX3')
    l2_current = await dm.read_register_client(DM, 31537, 'S32', device_id=2, sma_data_format='FIX3')
    l3_current = await dm.read_register_client(DM, 31539, 'S32', device_id=2, sma_data_format='FIX3')
    l1_power =   await dm.read_register_client(DM, 31505, 'S32', device_id=2, sma_data_format='FIX0')
    l2_power =   await dm.read_register_client(DM, 31507, 'S32', device_id=2, sma_data_format='FIX0')
    l3_power =   await dm.read_register_client(DM, 31509, 'S32', device_id=2, sma_data_format='FIX0')
    print(f'\tL1:\t{l1_current:.3f} A\t{l1_voltage:.2f} V\t{l1_power:.0f} W')
    print(f'\tL2:\t{l2_current:.3f} A\t{l2_voltage:.2f} V\t{l2_power:.0f} W')
    print(f'\tL3:\t{l3_current:.3f} A\t{l1_voltage:.2f} V\t{l3_power:.0f} W')


async def mode_1_loop():
    print(f'Mode 1 initializing')

    dm_cfg = config.get_data_manager_config()
    dm_cfg['name'] = DM

    while True:
        inverters = ModbusManager()
        dm = ModbusManager(client_configs=[dm_cfg])

        try:
            print(f'idle mode: connecting modbus clients')
            await inverters.connect()
            await dm.connect()

            print(f'idle: relinquish control and reset power set point')
            await inverters.write_registers(40149, [0, 0])  # reset rendement
            await inverters.write_registers(40151, [0, 803])  # 803 = inactive

            await battery_stats(inverters)
            await data_manager_stats(dm)

        except Exception as e:
            print(f'idle: encountered an error: {e}')

        finally:
            inverters.close()
            dm.close()

        await asyncio.sleep(10)
