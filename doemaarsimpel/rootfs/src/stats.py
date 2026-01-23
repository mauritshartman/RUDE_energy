from typing import Any
from prettytable import PrettyTable
from modbus import ModbusManager
from config import config
from log import log


DM = 'Data Manager'

REG_MAP = {
    'L1': { 'p': 30777, 'v': 30783, 'a': 30977 },
    'L2': { 'p': 30779, 'v': 30785, 'a': 30979 },
    'L3': { 'p': 30781, 'v': 30787, 'a': 30981 },
}

async def battery_stats(inverters: ModbusManager) -> dict[str, Any]:
    log(f'reading enabled inverter properties:')
    ret = {}

    temps_high = await inverters.read_registers_parallel(32221, 'S32', device_id=3, sma_format='TEMP')
    temps_low  = await inverters.read_registers_parallel(32227, 'S32', device_id=3, sma_format='TEMP')
    charges =    await inverters.read_registers_parallel(32233, 'U32', device_id=3, sma_format='FIX2')
    voltages =   await inverters.read_registers_parallel(30851, 'U32', device_id=3, sma_format='FIX2')
    currents =   await inverters.read_registers_parallel(30843, 'S32', device_id=3, sma_format='FIX3')

    for inv_name in temps_high.keys() & temps_low.keys() & charges.keys() & voltages.keys() & currents.keys():
        temp_h = temps_high[inv_name]
        temp_l = temps_low[inv_name]
        charge = charges[inv_name] * 10  # fix for now
        voltage = voltages[inv_name]
        current = currents[inv_name]

        # read phase specific values
        phi = config.inverter_config(inv_name)['connected_phase']
        ac_pow = await inverters.read_register(inv_name, REG_MAP[phi]['p'], 'S32', device_id=3, sma_format='FIX0')
        ac_vol = await inverters.read_register(inv_name, REG_MAP[phi]['v'], 'U32', device_id=3, sma_format='FIX2')
        ac_amp = await inverters.read_register(inv_name, REG_MAP[phi]['a'], 'S32', device_id=3, sma_format='FIX3')

        bat_stat = 'no flow'
        if ac_pow < 0:
            bat_stat = 'charging'
        elif ac_pow > 0:
            bat_stat = 'discharging'

        log(f'{inv_name} (connected to {phi}):')
        log(f'\tbattery:\t{current:.2f} A\t{voltage:.1f} V\t{bat_stat}\t{charge:.1f} %\t{temp_l} {chr(176)}C - {temp_h} {chr(176)}C')
        log(f'\tAC side:\t{ac_amp:.2f} A\t{ac_vol:.1f} V\t{ac_pow:.0f} W')

        ret[inv_name] = {
            'phase': phi,
            'battery': { 'A': current, 'V': voltage, 'status': bat_stat, 'charge': charge, 'temp_l': temp_l, 'temp_h': temp_h },
            'ac_side': { 'A': ac_amp, 'V': ac_vol, 'P': ac_pow },
        }
    return ret


async def data_manager_stats(dm: ModbusManager) -> dict[str, Any]:
    log(f'reading data manager properties:')
    l1_current = await dm.read_register(DM, 31535, 'S32', device_id=2, sma_format='FIX3')
    l2_current = await dm.read_register(DM, 31537, 'S32', device_id=2, sma_format='FIX3')
    l3_current = await dm.read_register(DM, 31539, 'S32', device_id=2, sma_format='FIX3')

    l1_voltage = await dm.read_register(DM, 31529, 'U32', device_id=2, sma_format='FIX2')
    l2_voltage = await dm.read_register(DM, 31531, 'U32', device_id=2, sma_format='FIX2')
    l3_voltage = await dm.read_register(DM, 31533, 'U32', device_id=2, sma_format='FIX2')

    l1_power =   await dm.read_register(DM, 31503, 'S32', device_id=2, sma_format='FIX0')
    l2_power =   await dm.read_register(DM, 31505, 'S32', device_id=2, sma_format='FIX0')
    l3_power =   await dm.read_register(DM, 31507, 'S32', device_id=2, sma_format='FIX0')

    l1_stat = ('no flow' if l1_power == 0 else ('drawing from grid' if l1_power < 0 else 'supplying to grid'))
    l2_stat = ('no flow' if l2_power == 0 else ('drawing from grid' if l2_power < 0 else 'supplying to grid'))
    l3_stat = ('no flow' if l3_power == 0 else ('drawing from grid' if l3_power < 0 else 'supplying to grid'))

    mf = config.get_data_manager_config()['max_fuse_current']

    table = PrettyTable()
    table.add_column('', ['Current', 'Max Current', 'Voltage', 'Power', 'Status'])
    table.add_column('L1', [f'{l1_current:.2f}', f'{mf} A', f'{l1_voltage:.1f} V', f'{l1_power:.0f} W', l1_stat])
    table.add_column('L2', [f'{l2_current:.2f}', f'{mf} A', f'{l2_voltage:.1f} V', f'{l2_power:.0f} W', l2_stat])
    table.add_column('L3', [f'{l3_current:.2f}', f'{mf} A', f'{l3_voltage:.1f} V', f'{l3_power:.0f} W', l3_stat])
    table.align['L1'] = 'r'
    table.align['L2'] = 'r'
    table.align['L3'] = 'r'
    log(table)

    return {
        'L1': { 'A': l1_current, 'Amax': mf, 'V': l1_voltage, 'P': l1_power, 'status': l1_stat },
        'L2': { 'A': l2_current, 'Amax': mf, 'V': l2_voltage, 'P': l2_power, 'status': l2_stat },
        'L3': { 'A': l3_current, 'Amax': mf, 'V': l3_voltage, 'P': l3_power, 'status': l3_stat },
    }