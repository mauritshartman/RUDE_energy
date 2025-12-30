import asyncio
from modbus import ModbusManager
# from config import config
from stats import DM, battery_stats, data_manager_stats


async def mode_1_loop():
    print(f'Mode 1 initializing')

    dm_cfg = config.get_data_manager_config()
    dm_cfg['name'] = DM

    while True:
        inverters = ModbusManager()
        dm = ModbusManager(client_configs=[dm_cfg])

        try:
            await inverters.connect()
            await dm.connect()

            print(f'idle: relinquish control and reset power set point')
            await inverters.write_registers_parallel(40149, [0, 0])  # reset rendement
            await inverters.write_registers_parallel(40151, [0, 803])  # 803 = inactive

            await battery_stats(inverters)
            await data_manager_stats(dm)

        except Exception as e:
            print(f'idle: encountered an error: {e}')

        finally:
            inverters.close()
            dm.close()

        await asyncio.sleep(config.get_loop_delay())
