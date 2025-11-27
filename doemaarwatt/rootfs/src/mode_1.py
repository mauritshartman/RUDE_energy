import asyncio
from modbus import ModbusManager
from config import config

EM = 'Energy Meter'

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


async def energy_meter_stats(em: ModbusManager):
    print(f'idle: reading energy meter properties:')

    freq = await em.read_register_client(EM, 31527, 'U32', device_id=2, sma_data_format='FIX2')
    print(f'\tgrid frequency: {freq:.2f} Hz')
    l1_voltage = await em.read_register_client(EM, 31529, 'U32', device_id=2, sma_data_format='FIX2')
    print(f'\tL1 voltage: {l1_voltage:.2f} V')
    l2_voltage = await em.read_register_client(EM, 31531, 'U32', device_id=2, sma_data_format='FIX2')
    print(f'\tL2 voltage: {l2_voltage:.2f} V')
    l3_voltage = await em.read_register_client(EM, 31533, 'U32', device_id=2, sma_data_format='FIX2')
    print(f'\tL3 voltage: {l3_voltage:.2f} V')
    l1_current = await em.read_register_client(EM, 31535, 'S32', device_id=2, sma_data_format='FIX3')
    print(f'\tL1 current: {l1_current:.3f} A')
    l2_current = await em.read_register_client(EM, 31537, 'S32', device_id=2, sma_data_format='FIX3')
    print(f'\tL2 current: {l1_current:.3f} A')
    l3_current = await em.read_register_client(EM, 31539, 'S32', device_id=2, sma_data_format='FIX3')
    print(f'\tL3 current: {l1_current:.3f} A')


async def mode_1_loop():
    print(f'Mode 1 initializing')

    em_cfg = config.get_energy_meter_config()
    em_cfg['name'] = EM

    while True:
        inverters = ModbusManager()
        em = ModbusManager(client_configs=[em_cfg])

        try:
            print(f'idle mode: connecting modbus clients')
            await inverters.connect()
            await em.connect()

            print(f'idle: relinquish control and reset power set point')
            await inverters.write_registers(40149, [0, 0])  # reset rendement
            await inverters.write_registers(40151, [0, 803])  # 803 = inactive

            await battery_stats(inverters)
            await energy_meter_stats(em)

        except Exception as e:
            print(f'idle: encountered an error: {e}')

        finally:
            inverters.close()
            em.close()

        await asyncio.sleep(10)
