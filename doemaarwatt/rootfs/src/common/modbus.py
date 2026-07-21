import asyncio
import struct
from typing import Any, Optional
from pymodbus.client import AsyncModbusTcpClient as MBClient
from pymodbus import ModbusException as PymodbusException
from pymodbus.pdu.pdu import ModbusPDU

from .logger import Logger
from .exceptions import DMWException, ConfigException, ProgrammingError


class ModbusException(DMWException):
    def __init__(self, message: str, source: str, requires_fallback: bool = False) -> None:
        super().__init__(message, source, requires_fallback)


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

# For each data type, SMA Modbus defines specific NaN values. Taken from 'SMAModbus-ennexOS-TI-en-13.pdf'
_modbus_nan_values = {
    'S16': -32768,
    'S32': -2147483648,
    'STR32': 0,
    'U16': 65535,
    'U32': 4294967295,
    'U32-status': 16777213,
    'U64': 18446744073709551615,
}


def value_is_nan(val: Any, dtype: str) -> bool:
    try:
        return val == _modbus_nan_values[dtype]
    except KeyError:
        return False


def to_s32_list(v: int) -> list[int]:
    '''Convert a signed 32-bit integer into a list of two unsigned 16-bit shorts'''
    r = struct.pack('>i', v)
    return list(struct.unpack('>HH', r))


def to_u32_list(v: int) -> list[int]:
    '''Convert an unsigned 32-bit integer into a list of two unsigned 16-bit shorts'''
    r = struct.pack('>I', abs(v))
    return list(struct.unpack('>HH', r))


class ModbusManager():

    def __init__(self,
        client_configs: list[dict[str, Any]],
        log: Logger,
    ):
        self.log = log

        self._clients: dict[str, Optional[MBClient]] = {}

        for cfg in client_configs:
            if len(cfg) == 0:
                continue
            if not cfg.get('enable', True): # eg. skip disabled inverters
                continue

            name = cfg['name']
            if cfg['host'].lower() in ['test', 'debug', 'none']:
                self.log.debug(f'modbus[{name}]: creating dummy client')
                self._clients[name] = None
            else:
                self.log.debug(f'modbus[{name}]: creating modbus client')
                self._clients[name] = MBClient(
                    cfg['host'],
                    port=int(cfg.get('port', 502)),
                    name=f'Modbus[{name}]',
                    reconnect_delay=10.0,  # TODO: make config setting
                    timeout=5,
                )

    async def connect(self):
        for name, client in self._clients.items():
            if client is None:
                continue
            await client.connect()
            if not client.connected:
                raise ModbusException(f'unable to connect', source=f'modbus:{name}')
            self.log.debug(f'[modbus:{name}]: connected')

    def close(self):
        for name, client in self._clients.items():
            if client is None:
                continue
            client.close()
            self.log.debug(f'[modbus:{name}]: closed connection')

    async def write_registers_parallel(self,
        address: int,
        values: list[int],
        no_response_expected: bool = False,
    ):
        for name, client in self._clients.items():
            self.log.debug(f'[modbus:{name}]: write register {address} <- {values}')

            if client is None:
                continue

            await client.write_registers(
                address,
                values,
                device_id=3,  # related to Unit_id
                no_response_expected=no_response_expected,
            )

    async def write_register(self,
        client_name: str,
        address: int,
        values: list[int],
        no_response_expected: bool = False,
        device_id: int = 3,
    ):
        if not client_name in self._clients:
            raise ConfigException(f'client name {client_name} not configured', source=f'modbus:{client_name}')
        self.log.debug(f'[modbus:{client_name}]: write register {address} <- {values}')

        client = self._clients[client_name]
        if client is None:
            return

        await client.write_registers(address, values, device_id=device_id, no_response_expected=no_response_expected)

    async def read_register(self,
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
            return 1.2345  # dummy value

        try:
            cnt = self._dtype_to_word_count(dtype)
            self.log.debug(f'[modbus:{client_name}]: trying to read register {address} (count: {cnt})')

            resp: Optional[ModbusPDU] = None
            if str(address)[0] == '4':
                resp = await client.read_holding_registers(address, count=cnt, device_id=device_id)
            elif str(address)[0] == '3':
                resp = await client.read_input_registers(address, count=cnt, device_id=device_id)
            else:
                raise ProgrammingError(f'this method only supports reading input and holding registers', source=f'modbus:{client_name}')

            if resp.isError():
                code = getattr(resp, 'exception_code', None)
                if code:
                    exc_descr = _modbus_exception_codes.get(resp.exception_code, '<unknown exception>')
                    raise ModbusException(f'error while reading: ({code}) {exc_descr}', source=f'modbus:{client_name}')

            value = self._decode_response(client_name, dtype, resp, sma_format=sma_format)
            self.log.debug(f'[modbus:{client_name}]: read register {address} -> {value}')
            return value

        except PymodbusException as e:
            raise ModbusException(f'exception in Pymodbus library while reading: {e}', source=f'modbus:{client_name}')

    async def read_register_seq(self,
        client_name: str,
        addr: list[tuple[int, str, str]],
        device_id: int = 3,
    ) -> list[Any]:
        '''
        Perform sequential reads on a holding or input register using the client connected to client name
        The addr argument must be a list of 3-tuples, each specifying (modbus address, data type, SMA format)
        '''
        assert isinstance(addr, list)

        ret = []
        for address, dtype, sma_format in addr:
            ret.append(await self.read_register(client_name, address, dtype, device_id=device_id, sma_format=sma_format))

        return ret

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
            self.log.debug(f'[modbus:{client_name}]: trying to read register {address} (count: {cnt})')

            reg_digit = str(address)[0]
            if reg_digit == '4':
                resp = await client.read_holding_registers(address, count=cnt, device_id=device_id)
            elif reg_digit == '3':
                resp = await client.read_input_registers(address, count=cnt, device_id=device_id)
            else:
                raise ProgrammingError(f'this method only supports reading input and holding registers ({address})', source=f'modbus:{client_name}')

            if resp.isError():
                code = getattr(resp, 'exception_code', None)
                if code:
                    exc_descr = _modbus_exception_codes.get(resp.exception_code, '<unknown exception>')
                    raise ModbusException(f'error while reading: ({code}) {exc_descr}', source=f'modbus:{client_name}')
                else:
                    raise ModbusException(f'error while reading: (code absent) {resp}', source=f'modbus:{client_name}')

            value = self._decode_response(client_name, dtype, resp, sma_format=sma_format)
            result_dict[client_name] = value
            self.log.debug(f'[modbus:{client_name}]: read register {address} -> {value}')

        except PymodbusException as e:
            raise ModbusException(f'exception in Pymodbus library while reading: {e}', source=f'modbus:{client_name}')

    async def read_registers_parallel(self,
        address: int,
        dtype: str,
        device_id: int = 3,
        sma_format: str | dict[int, str] | None = None,
        raise_exceptions: bool = True,
    ) -> dict[str, Any]:
        '''Perform a parallel register read operation across all clients'''
        ret = {}  # collect results here

        tasks = []
        task_names = []
        for name, client in self._clients.items():
            if client is None:
                ret[name] = 1.2345  # dummy value
                continue
            tasks.append(self._read_registers(name, address, dtype, ret, device_id=device_id, sma_format=sma_format))
            task_names.append(name)

        if raise_exceptions:
            # default behavior: propagate any exceptions
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                self.log.error(f'modbus: Modbus parallel read failed: {e}')
                self.close()
                if isinstance(e, ModbusException):
                    raise
                else: # wrap
                    raise ModbusException(f'error: {e}', source=f'modbus')

        else:
            # figure out which modbus reads failed and mark those with a None value
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception): # mark a None value in the return dict
                    name = task_names[i]
                    self.log.error(f'[modbus:{name}]: exception while reading {address}: {result}')
                    ret[name] = None

        return ret

    def _dtype_to_word_count(self, dtype: str) -> int:
        dtype = dtype.upper()
        if dtype == 'U16':
            return 1
        elif dtype == 'S16':
            return 1
        elif dtype == 'U32':
            return 2
        elif dtype == 'U32-status':
            return 2
        elif dtype == 'S32':
            return 2
        elif dtype == 'U64':
            return 4
        elif dtype == 'S64':
            return 4
        raise ProgrammingError(f'unrecognized Modbus datatype: {dtype}', source='modbus')

    def _decode_response(self,
        client_name: str,
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

        if value_is_nan(value, dtype):
            self.log.info(f'[modbus:{client_name}]: decoded modbus response {value} into a NaN-value')
            return None  # we use None as NaN

        if sma_format is not None:
            if isinstance(sma_format, str):
                sma_format = sma_format.upper()
                if sma_format == 'FIX0':
                    pass  # no decimal place, so no rounding needed
                elif sma_format == 'FIX1':
                    value = float(value) / 1e1  # type: ignore
                elif sma_format == 'FIX2':
                    value = float(value) / 1e2  # type: ignore
                elif sma_format == 'FIX3':
                    value = float(value) / 1e3  # type: ignore
                elif sma_format == 'TEMP':
                    value = float(value) / 1e1  # type: ignore
            elif isinstance(sma_format, dict):  # assuming data format is a tag list mapping
                try:
                    value = sma_format[value]  # type: ignore
                except KeyError:
                    raise ProgrammingError(f'no taglist mapping for value {value}', source='modbus')

        self.log.debug(f"[modbus:{client_name}]: decoded response '{resp}' into {value}")
        return value
