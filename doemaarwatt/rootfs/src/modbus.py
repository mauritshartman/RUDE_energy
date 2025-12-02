from pymodbus.client import AsyncModbusTcpClient as MBClient
from pymodbus import ModbusException
import asyncio
from config import config
from typing import Any


_modbus_exception_codes = {
    0x01: "Illegal Function - Function code not supported",
    0x02: "Illegal Data Address - Address not allowed",
    0x03: "Illegal Data Value - Value out of range",
    0x04: "Slave Device Failure - Device error",
    0x05: "Acknowledge - Request accepted, processing",
    0x06: "Slave Device Busy - Try again later",
    0x08: "Memory Parity Error - Device memory error",
    0x0A: "Gateway Path Unavailable - Gateway error",
    0x0B: "Gateway Target Failed - Target not responding"
}


class ModbusManager():

    def __init__(self,
        client_configs: list[dict[str, Any]] | None = None,
    ):
        self._debug: bool = config.get_debug()

        self._clients: dict[str, MBClient] = {}

        if client_configs is None:
            for inv_name in config.get_inverter_names():
                inv_config = config.inverter_config(inv_name)

                if inv_config['host'].lower() in ['test', 'debug', 'none']:
                    self.debug(f'DEBUG: creating dummy client for {inv_name}')
                    self._clients[inv_name] = None
                else:
                    self.debug(f'DEBUG: creating modbus client for {inv_name}')
                    self._clients[inv_name] = MBClient(
                        inv_config['host'],
                        port=int(inv_config['port']),
                        name=f'Modbus[{inv_name}]',
                        reconnect_delay=f'10.0',  # TODO: make config setting
                        timeout=5,
                    )
        else:
            for cfg in client_configs:
                name = cfg['name']
                if cfg['host'].lower() in ['test', 'debug', 'none']:
                    self.debug(f'DEBUG: creating dummy client for {name}')
                    self._clients[name] = None
                else:
                    self.debug(f'DEBUG: creating modbus client for {name}')
                    self._clients[name] = MBClient(
                        cfg['host'],
                        port=int(cfg.get('port', 502)),
                        name=f'Modbus[{name}]',
                        reconnect_delay=f'10.0',  # TODO: make config setting
                        timeout=5,
                    )

    def debug(self, msg: str):
        if self._debug:
            print(msg)

    async def connect(self):
        for name, client in self._clients.items():
            self.debug(f'DEBUG: connecting to inverter {name}')
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
        values: list[int],
        no_response_expected: bool = False,
    ):
        for name, client in self._clients.items():
            self.debug(f'DEBUG: Modbus[{name}] write registers {address} -> {values}')
            if client is None:
                continue
            await client.write_registers(
                address,
                values,
                device_id=3,  # battery-management also uses slave=3. Perhaps related to Unit ID in datasheet?
                no_response_expected=no_response_expected,
            )

    async def read_register_client(self,
        client_name: str,
        address: int,
        dtype: str,
        device_id: int = 3,
        sma_format: str | dict[int, str] | None = None,
    ) -> Any:
        '''
        Read a holding or input register using the named client connected to client_name
        The following logic is used to determine whether the register is a holding or input register:

        3x = Input Register = 30001-39999
        4x = Holding Register = 40001-49999
        '''
        client = self._clients.get(client_name)
        if client is None:
            return 12345  # dummy value

        try:
            cnt = self._dtype_to_word_count(dtype)
            self.debug(f'DEBUG: Modbus[{client_name}] trying to read register {address} (count: {cnt})')

            if str(address)[0] == '4':
                resp = await client.read_holding_registers(address, count=cnt, device_id=device_id)
            elif str(address)[0] == '3':
                resp = await client.read_input_registers(address, count=cnt, device_id=device_id)

            if resp.isError():
                code = getattr(resp, 'exception_code', None)
                if code:
                    exc_descr = _modbus_exception_codes.get(resp.exception_code, '<unknown exception>')
                    raise Exception(f'modbus error while reading from {client_name}: ({code}) {exc_descr}')

            value = self._decode_response(dtype, resp, sma_format=sma_format)
            self.debug(f'DEBUG: Modbus[{client_name}] read register {address} -> {value}')
            return value

        except ModbusException as e:
            raise Exception(f'internal exception in Pymodbus library while reading from {client_name}: {e}')

    async def _read_registers(self,
        client_name: str,
        address: int,
        dtype: str,
        result_dict: dict[str, Any],
        device_id: int = 3,
        sma_format: str | dict[int, str] | None = None,
    ):
        '''
        Read a holding or input register using the client connected to client_name
        The following logic is used to determine whether the register is a holding or input register:

        3x = Input Register = 30001-39999
        4x = Holding Register = 40001-49999
        '''
        result_dict[client_name] = None  # ensure some value is present
        client = self._clients.get(client_name)
        if client is None:
            return

        try:
            cnt = self._dtype_to_word_count(dtype)
            self.debug(f'DEBUG: Modbus[{client_name}] trying to read register {address} (count: {cnt})')

            if str(address)[0] == '4':
                resp = await client.read_holding_registers(address, count=cnt, device_id=device_id)
            elif str(address)[0] == '3':
                resp = await client.read_input_registers(address, count=cnt, device_id=device_id)

            if resp.isError():
                code = getattr(resp, 'exception_code', None)
                if code:
                    exc_descr = _modbus_exception_codes.get(resp.exception_code, '<unknown exception>')
                    raise Exception(f'modbus error while reading from {client_name}: ({code}) {exc_descr}')

            value = self._decode_response(dtype, resp, sma_format=sma_format)
            result_dict[client_name] = value
            self.debug(f'DEBUG: Modbus[{client_name}] read register {address} -> {value}')

        except ModbusException as e:
            raise Exception(f'internal exception in Pymodbus library while reading from {client_name}: {e}')

    async def read_registers(self,
        address: int,
        dtype: str,
        device_id: int = 3,
        sma_format: str | dict[int, str] | None = None,
    ) -> dict[str, Any]:
        '''Perform a parallel register read operation across all clients'''
        ret = {}  # collect results here

        tasks = []
        for name, client in self._clients.items():
            if client is None:
                ret[name] = 12435  # dummy value
                continue
            tasks.append(self._read_registers(name, address, dtype, ret, device_id=device_id, sma_format=sma_format))

        try:
            await asyncio.gather(*tasks)  # exceptions raised within a task will propagate
        except Exception as e:
            self.debug(f'DEBUG: Modbus parallel read failed: {e}')
            self.close()
            raise

        return ret

    def _dtype_to_word_count(self, dtype: str) -> int:
        dtype = dtype.upper()
        if dtype == 'U16':
            return 1
        elif dtype == 'S16':
            return 1
        elif dtype == 'U32':
            return 2
        elif dtype == 'S32':
            return 2
        elif dtype == 'U64':
            return 4
        elif dtype == 'S64':
            return 4
        raise Exception(f'unrecognized Modbus datatype: {dtype}')

    def _decode_response(self,
        dtype: str,
        resp,
        sma_format: str | dict[int, str] | None = None,
    ) -> Any:
        '''
        Decode a non-error modbus server response according to the datatype, applying proper endianness, etc
        See https://www.pymodbus.org/docs/reading-registers#working-with-different-data-types
        '''
        dtype = dtype.upper()
        if dtype == 'U16':
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.UINT16, 'big')
        elif dtype == 'S16':
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.INT16, 'big')
        elif dtype == 'U32':
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.UINT32, 'big')
        elif dtype == 'S32':
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.INT32, 'big')
        elif dtype == 'U64':
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.UINT64, 'big')
        else:  # TODO expand for STR32 type and variable length strings
            return resp

        if sma_format is not None:
            sma_format = sma_format.upper()
            if sma_format == 'FIX0':
                pass  # no decimal place, so no rounding needed
            elif sma_format == 'FIX1':
                value = float(value) / 1e1
            elif sma_format == 'FIX2':
                value = float(value) / 1e2
            elif sma_format == 'FIX3':
                value = float(value) / 1e3
            elif sma_format == 'TEMP':
                value = float(value) / 1e1
            elif isinstance(sma_format, dict):  # assuming data format is a tag list mapping
                try:
                    value = sma_format[value]
                except KeyError:
                    raise Exception(f'no taglist mapping for value {value}')

        self.debug(f"DEBUG: decoded response '{resp}' into {value}")
        return value
