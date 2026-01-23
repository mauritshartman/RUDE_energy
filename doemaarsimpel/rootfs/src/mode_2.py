import asyncio
from prettytable import PrettyTable
from modbus import ModbusManager, to_s32_list
from config import config
from stats import DM, battery_stats, data_manager_stats
from pbsent import calc_PBsent
from log import log

async def mode_2_loop():
    log(f'Mode 2 (manual mode) initializing')

    dm_cfg = config.get_data_manager_config()
    dm_cfg['name'] = DM

    inv_phase_map = config.get_inverter_phase_map()
    log(f'manual mode: the following inverters are enabled for each phase:')
    for phase, inverter_names in inv_phase_map.items():
        name_list = 'no inverter enabled' if len(inverter_names) == 0 else ', '.join(inverter_names)
        log(f'\t{phase}:\t{name_list}')

    manual_mode_config = config.get_manual_mode_config()
    charge_amount = -1 * abs(manual_mode_config['amount']) if manual_mode_config['charge'] else abs(manual_mode_config['amount'])
    PBapp_phases = { phase: (charge_amount if len(inv_names) > 0 else 0) for phase, inv_names in inv_phase_map.items() }
    log(f'manual mode: charging configuration for each phase:')
    for phase, charge in PBapp_phases.items():
        log(f'\tPBapp_{phase}:\t{charge / 1e3:.1f} kW')


    while True:
        inverters = ModbusManager()
        dm = ModbusManager(client_configs=[dm_cfg])  # data manager modbus connection

        try:
            log(f'manual mode: connecting and assuming control')
            await inverters.connect()
            await dm.connect()
            await inverters.write_registers_parallel(40151, [0, 802])  # 802 = active

            # get necessary stats
            inv_stats = await battery_stats(inverters)
            dm_stats = await data_manager_stats(dm)

            # determine PBsent for each phase
            log(f'manual mode: computing safe charge/discharge amount (PBsent) for each phase:')
            PBsent_phases = {}
            table = PrettyTable()
            table.add_column('', ['PBapp', 'PBnow', 'PGnow', 'VGnow', 'Imax', 'PGmax', 'PGmin', 'Pother', 'PBlim_min', 'PBlim_max', 'PBsent'])

            for phi in ['L1', 'L2', 'L3']:
                PBapp = PBapp_phases[phi]
                if PBapp == 0:
                    table.add_column(phi, ['no charge/discharge set', '', '', '', '', '', '', '', '', '', 'nothing sent'])
                    continue

                PGnow = dm_stats[phi]['P']  # negative: drawing power from the grid
                VGnow = dm_stats[phi]['V']
                Imax = dm_stats[phi]['Amax'] # eg. 25A main fuse
                PGmax = VGnow * Imax
                PBnow = sum(v['ac_side']['P'] for v in inv_stats.values() if v['phase'] == phi)  # total power of all inverters on phase

                PBsent_phases[phi] = calc_PBsent(PBapp, PBnow, PGnow, VGnow, Imax, col_header=phi, table=table)
            log(table)

            log(f'manual mode: sending charge/discharge amount (PBsent) to enabled inverters:')
            for phi, PBsent in PBsent_phases.items():
                if PBsent < 0:  # negative: so charge
                    for inv_name in inv_phase_map[phi]:
                        log(f'commanding {inv_name} to charge at {PBsent:.0f} W')
                        await inverters.write_register(inv_name, 40149, to_s32_list(PBsent))
                else:  # zero or positive: so discharge
                    for inv_name in inv_phase_map[phi]:
                        log(f'commanding {inv_name} to discharge at {PBsent:.0f} W')
                        await inverters.write_register(inv_name, 40149, to_s32_list(PBsent))

        except Exception as e:
            log(f'manual mode: encountered an error: {e}')

        finally:
            inverters.close()
            dm.close()

        await asyncio.sleep(config.get_loop_delay())