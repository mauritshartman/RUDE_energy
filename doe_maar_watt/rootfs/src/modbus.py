from pymodbus.client import AsyncModbusTcpClient
from config import config
from typing import Dict, List


class ModbusManager():

    def __init__(self):
        self._clients: Dict[str, AsyncModbusTcpClient] = {}
        for inv_name in config.get_inverter_names():
            inv_config = config.inverter_config(inv_name)
            if inv_config['host'].lower() in ['test', 'debug']:
                print(f'DEBUG: creating dummy client for {inv_name}')
                self._clients[inv_name] = None
            else:
                print(f'DEBUG: creating modbus client for {inv_name}')
                self._clients[inv_name] = AsyncModbusTcpClient(
                    inv_config['host'],
                    port=int(inv_config['port']),
                    name=f'Modbus[{inv_name}]',
                    reconnect_delay=f'10.0',  # TODO: make config setting
                    timeout=5,
                )

    async def connect(self):
        for name, client in self._clients.items():
            print(f'DEBUG: connecting to inverter {name}')
            if client is None:
                continue
            await client.connect()
            if not client.connected:
                raise Exception(f'unable to connect to inverter {name}')

    def close(self):
        for client in self._clients.values():
            if client is None:
                continue
            client.close()

    async def write_registers(self,
        address: int,
        values: List[int],
        no_response_expected: bool = False,
    ):
        for name, client in self._clients.items():
            print(f'DEBUG: Modbus[{name}] write registers {address} -> {values}')
            if client is None:
                continue
            await client.write_registers(
                address,
                values,
                device_id=3,  # battery-management also uses slave=3. Perhaps related to Unit ID in datasheet?
                no_response_expected=no_response_expected,
            )
