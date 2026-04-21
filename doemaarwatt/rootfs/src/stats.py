from typing import Any, Optional
from enum import StrEnum

from prettytable import PrettyTable
from modbus import ModbusManager
from logger import Logger


DM = 'Data Manager'
SI = 'Solar Inverter'

REG_MAP = {
    'L1': { 'p': 30777, 'v': 30783, 'a': 30977 },
    'L2': { 'p': 30779, 'v': 30785, 'a': 30979 },
    'L3': { 'p': 30781, 'v': 30787, 'a': 30981 },
}


class ControlStatus(StrEnum):
    UNCONTROLLED = 'UNCONTROLLED' # battery inverter, solar inverter or data manager is currently not being controlled
    NOMINAL = 'NOMINAL' # inverter or data manager is fully controlled
    DEGRADED = 'DEGRADED' # inverter or data manager is only partially being controlled: only some registers could be read/written and/or a NaN value is returned


async def battery_stats(
    inverters: ModbusManager,
    phase_map: dict[str, str],
    log: Optional[Logger] = None,
) -> dict[str, Any]:
    if log:
        log.debug(f'reading enabled inverter properties:\n{phase_map}')

    ret = {}

    temps_high = await inverters.read_registers_parallel(32221, 'S32', device_id=3, sma_format='TEMP')
    temps_low  = await inverters.read_registers_parallel(32227, 'S32', device_id=3, sma_format='TEMP')
    charges =    await inverters.read_registers_parallel(32233, 'U32', device_id=3, sma_format='FIX2')
    voltages =   await inverters.read_registers_parallel(30851, 'U32', device_id=3, sma_format='FIX2')
    currents =   await inverters.read_registers_parallel(30843, 'S32', device_id=3, sma_format='FIX3')

    for inv_name in temps_high.keys() & temps_low.keys() & charges.keys() & voltages.keys() & currents.keys():
        temp_h = temps_high[inv_name]
        temp_l = temps_low[inv_name]
        charge = charges[inv_name]
        if not charge is None:
            charge *= 10  # fix for now
        voltage = voltages[inv_name]
        current = currents[inv_name]

        # read phase specific values
        phi = phase_map[inv_name]
        ac_pow = await inverters.read_register(inv_name, REG_MAP[phi]['p'], 'S32', device_id=3, sma_format='FIX0')
        ac_vol = await inverters.read_register(inv_name, REG_MAP[phi]['v'], 'U32', device_id=3, sma_format='FIX2')
        ac_amp = await inverters.read_register(inv_name, REG_MAP[phi]['a'], 'S32', device_id=3, sma_format='FIX3')

        bat_stat = 'standby'
        if charge is None:
            bat_stat = 'disconnected'
        elif ac_pow < 0:
            bat_stat = 'charging'
        elif ac_pow > 0:
            bat_stat = 'discharging'

        if log:
            log.debug(f'{inv_name} (connected to {phi}):')
            if current is None or voltage is None or ac_amp is None or ac_vol is None or ac_pow is None:
                log.error(f'\tbattery:\t{current} A\t{voltage} V\t{bat_stat}\t - \t{temp_l} {chr(176)}C - {temp_h} {chr(176)}C')
                log.error(f'\tAC side:\t{ac_amp} A\t{ac_vol} V\t{ac_pow} W')
            else:
                if charge is None:
                    log.debug(f'\tbattery:\t{current:.2f} A\t{voltage:.1f} V\t{bat_stat}\t - \t{temp_l} {chr(176)}C - {temp_h} {chr(176)}C')
                else:
                    log.debug(f'\tbattery:\t{current:.2f} A\t{voltage:.1f} V\t{bat_stat}\t{charge:.1f} %\t{temp_l} {chr(176)}C - {temp_h} {chr(176)}C')
                log.debug(f'\tAC side:\t{ac_amp:.2f} A\t{ac_vol:.1f} V\t{ac_pow:.0f} W')

        control_status = ControlStatus.NOMINAL
        if any(v is None for v in [temp_h, temp_l, charge, voltage, current, ac_pow, ac_vol, ac_amp]):
            control_status = ControlStatus.DEGRADED

        ret[inv_name] = {
            'phase': phi,
            'control_status': control_status,
            'battery': { 'A': current, 'V': voltage, 'status': bat_stat, 'charge': charge, 'temp_l': temp_l, 'temp_h': temp_h },
            'ac_side': { 'A': ac_amp, 'V': ac_vol, 'P': ac_pow },
        }
    return ret


async def solar_inverter_stats(
    si: ModbusManager,
    device_id: int = 3,
    log: Optional[Logger] = None,
) -> dict[str, Any]:
    if log:
        log.debug(f'reading solar inverter properties:')

    total_power = await si.read_register(SI, 30775, 'S32', device_id=device_id, sma_format='FIX0')
    l1_power = await si.read_register(SI, 30777, 'S32', device_id=device_id, sma_format='FIX0')
    l2_power = await si.read_register(SI, 30779, 'S32', device_id=device_id, sma_format='FIX0')
    l3_power = await si.read_register(SI, 30781, 'S32', device_id=device_id, sma_format='FIX0')
    current_setpoint_limit = await si.read_register(SI, 31405, 'U32', device_id=device_id, sma_format='FIX0')

    if log:
        table = PrettyTable()
        table.add_column('', ['Power'])

        if l1_power is None or l2_power is None or l3_power is None or total_power is None:
            table.add_column('L1', [f'{l1_power} W'])
            table.add_column('L2', [f'{l2_power} W'])
            table.add_column('L3', [f'{l3_power} W'])
            table.add_column('total', [f'{total_power} W'])
        else:
            table.add_column('L1', [f'{l1_power:.0f} W'])
            table.add_column('L2', [f'{l2_power:.0f} W'])
            table.add_column('L3', [f'{l3_power:.0f} W'])
            table.add_column('total', [f'{total_power:.0f} W'])

        if current_setpoint_limit is None:
            table.add_column('setpoint limit', [f'not set'])
        else:
            table.add_column('setpoint limit', [f'{current_setpoint_limit:.0f} W'])

        table.align['L1'] = 'r'
        table.align['L2'] = 'r'
        table.align['L3'] = 'r'
        table.align['total'] = 'r'
        table.align['setpoint limit'] = 'r'
        log.debug(str(table))

    control_status = ControlStatus.NOMINAL
    if any(v is None for v in [total_power, l1_power, l2_power, l3_power, current_setpoint_limit]):
        control_status = ControlStatus.DEGRADED

    return {
        'L1': { 'P': l1_power },
        'L2': { 'P': l2_power },
        'L3': { 'P': l3_power },
        'control_status': control_status,
        'total_power': total_power,
        'setpoint_limit': current_setpoint_limit,
    }


async def data_manager_stats(
    dm: ModbusManager,
    max_fuse: int,
    log: Optional[Logger] = None,
) -> dict[str, Any]:
    if log:
        log.debug(f'reading data manager properties:')
    l1_current = await dm.read_register(DM, 31535, 'S32', device_id=2, sma_format='FIX3')
    l2_current = await dm.read_register(DM, 31537, 'S32', device_id=2, sma_format='FIX3')
    l3_current = await dm.read_register(DM, 31539, 'S32', device_id=2, sma_format='FIX3')

    l1_voltage = await dm.read_register(DM, 31529, 'U32', device_id=2, sma_format='FIX2')
    l2_voltage = await dm.read_register(DM, 31531, 'U32', device_id=2, sma_format='FIX2')
    l3_voltage = await dm.read_register(DM, 31533, 'U32', device_id=2, sma_format='FIX2')

    l1_power =   await dm.read_register(DM, 31503, 'S32', device_id=2, sma_format='FIX0')
    l2_power =   await dm.read_register(DM, 31505, 'S32', device_id=2, sma_format='FIX0')
    l3_power =   await dm.read_register(DM, 31507, 'S32', device_id=2, sma_format='FIX0')

    l1_stat = ('no flow / disconnected' if l1_power == 0 or l1_power is None else ('drawing from grid' if l1_power < 0 else 'supplying to grid'))
    l2_stat = ('no flow / disconnected' if l2_power == 0 or l2_power is None else ('drawing from grid' if l2_power < 0 else 'supplying to grid'))
    l3_stat = ('no flow / disconnected' if l3_power == 0 or l3_power is None else ('drawing from grid' if l3_power < 0 else 'supplying to grid'))

    mf = max_fuse

    if log:
        table = PrettyTable()
        table.add_column('', ['Current', 'Max Current', 'Voltage', 'Power', 'Status'])

        if l1_current is None or l1_voltage is None or l1_power is None:
            table.add_column('L1', [f'{l1_current}', f'{mf} A', f'{l1_voltage}', f'{l1_power}', l1_stat])
        else:
            table.add_column('L1', [f'{l1_current:.2f}', f'{mf} A', f'{l1_voltage:.1f} V', f'{l1_power:.0f} W', l1_stat])

        if l2_current is None or l2_voltage is None or l2_power is None:
            table.add_column('L2', [f'{l2_current}', f'{mf} A', f'{l2_voltage}', f'{l2_power}', l2_stat])
        else:
            table.add_column('L2', [f'{l2_current:.2f}', f'{mf} A', f'{l2_voltage:.1f} V', f'{l2_power:.0f} W', l2_stat])

        if l3_current is None or l3_voltage is None or l3_power is None:
            table.add_column('L3', [f'{l3_current}', f'{mf} A', f'{l3_voltage}', f'{l3_power}', l3_stat])
        else:
            table.add_column('L3', [f'{l3_current:.2f}', f'{mf} A', f'{l3_voltage:.1f} V', f'{l3_power:.0f} W', l3_stat])

        table.align['L1'] = 'r'
        table.align['L2'] = 'r'
        table.align['L3'] = 'r'
        log.debug(str(table))

    control_status = ControlStatus.NOMINAL
    if any(v is None for v in [
        l1_current, l2_current, l3_current,
        l1_voltage, l2_voltage, l3_voltage,
        l1_power, l2_power, l3_power,
        l1_stat, l2_stat, l3_stat]):
        control_status = ControlStatus.DEGRADED

    return {
        'control_status': control_status,
        'L1': { 'A': l1_current, 'Amax': mf, 'V': l1_voltage, 'P': l1_power, 'status': l1_stat },
        'L2': { 'A': l2_current, 'Amax': mf, 'V': l2_voltage, 'P': l2_power, 'status': l2_stat },
        'L3': { 'A': l3_current, 'Amax': mf, 'V': l3_voltage, 'P': l3_power, 'status': l3_stat },
    }
