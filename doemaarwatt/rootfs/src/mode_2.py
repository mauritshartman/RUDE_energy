import asyncio
from prettytable import PrettyTable
from modbus import ModbusManager
from config import config
from stats import DM, battery_stats, data_manager_stats

async def mode_2_loop():
    print(f'Mode 2 (manual charge) initializing')

    dm_cfg = config.get_data_manager_config()
    dm_cfg['name'] = DM

    inv_phase_map = config.get_inverter_phase_map()
    print(f'manual charging: the following inverters are enabled for each phase:')
    for phase, inverter_names in inv_phase_map.items():
        name_list = 'no inverter enabled' if len(inverter_names) == 0 else ', '.join(inverter_names)
        print(f'\t{phase}:\t{name_list}')

    charge_amount = config.get_charge_amount()
    PBapp_phases = { phase: (charge_amount if len(inv_names) > 0 else 0) for phase, inv_names in inv_phase_map.items() }
    print(f'manual charging: charging configuration for each phase:')
    for phase, charge in PBapp_phases.items():
        print(f'\tPBapp_{phase}:\t{charge / 1e3:.1f} kW')


    while True:
        inverters = ModbusManager()
        dm = ModbusManager(client_configs=[dm_cfg])  # data manager modbus connection

        try:
            print(f'manual charging: connecting and assuming control')
            await inverters.connect()
            await dm.connect()
            await inverters.write_registers_parallel(40151, [0, 802])  # 802 = active

            # get necessary stats
            inv_stats = await battery_stats(inverters)
            dm_stats = await data_manager_stats(dm)

            # determine PBsent for each phase
            print(f'manual charging: determining PBsent for each phase:')
            PBsent_phases = {}
            table = PrettyTable()
            table.add_column('', ['PBapp', 'VGnow', 'Imax', 'PGmax', 'PGnow', 'PBnow', 'PBlim', 'PBsent'])
            for phi in ['L1', 'L2', 'L3']:
                PBapp = PBapp_phases[phi]
                if PBapp == 0:
                    table.add_column(phi, [PBapp, VGnow, Imax, PGmax, PGnow, '', '', 'disabled'])
                    continue
                PGnow = dm_stats[phi]['P']  # negative: drawing power from the grid
                VGnow = dm_stats[phi]['V']
                Imax = dm_stats[phi]['Amax'] # eg. 25A main fuse
                PGmax = VGnow * Imax
                PBnow = sum(v['ac_side']['P'] for v in inv_stats.values() if v['phase'] == phi)  # total power of all inverters on phase
                PBlim = PGmax - PGnow + PBnow
                PBsent = int(min(PBapp, PBlim))
                PBsent_phases[phi] = PBsent

                table.add_column(phi, [f'{PBapp} W', f'{VGnow:.2f} V', f'{Imax} A', f'{PGmax:.0f} W', f'{PGnow:.0f} W', f'{PBnow:.0f} W', f'{PBlim:.0f} W', f'{PBsent:.0f} W'])
            print(table)

            print(f'manual charging: sending charge amount (PBsent) to enabled inverters:')
            for phi, PBsent in PBapp_phases.items():
                if PBsent > 0:
                    for inv_name in inv_phase_map[phi]:
                        print(f'commanding {inv_name} to charge at {PBsent:.0f} W')
                        await inverters.write_register(inv_name, 40149, [65535, 65535 - charge_amount])

        except Exception as e:
            print(f'manual charging: encountered an error: {e}')

        finally:
            inverters.close()
            dm.close()

        await asyncio.sleep(config.get_loop_delay())
