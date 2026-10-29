import asyncio
import math
import struct
from typing import Any, NamedTuple, Optional
from pymodbus.client import AsyncModbusTcpClient as MBClient
from pymodbus import ModbusException as PymodbusException
from pymodbus.pdu.pdu import ModbusPDU

from .logger import Logger
from .exceptions import DMWException, ConfigException, ProgrammingError


class _BatchField(NamedTuple):
    '''One value requested from a batch read: where it lives, how to decode it, and where it belongs in the
    list the caller gets back (which follows the order it asked in, not the order of the addresses).
    '''
    result_index: int   # not 'index': a NamedTuple field of that name would replace tuple.index()
    address: int
    dtype: str
    sma_format: Any
    words: int
    holding: bool


class _RegisterSlice(NamedTuple):
    '''The registers of one value, cut out of the response of the grouped read it arrived in. Carries the one
    attribute _decode_response reads, so a batched value is decoded exactly like a singly read one.
    '''
    registers: list[int]

    def isError(self) -> bool:
        return False


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
    'S16': -32768, # 0x8000
    'S32': -2147483648, # 0x8000 0000
    'STR32': 0,
    'U16': 65535, # 0xFFFF
    'U32': 4294967295, # 0xFFFF FFFF
    'U32-STATUS': 16777213, # 0xFFFF FD
    'U64': 18446744073709551615,
}


def value_is_nan(val: Any, dtype: str) -> bool:
    if isinstance(val, float):
        return math.isnan(val)

    if val is None and dtype == 'STRING':
        return True

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

            val_str = '[' + ','.join(str(v) for v in values) + ']'

            try:
                await client.write_registers(
                    address,
                    values,
                    device_id=3,  # related to Unit_id
                    no_response_expected=no_response_expected,
                )
                self.log.debug(f'[modbus:{name}]: write register {address} <- {val_str}')
            except PymodbusException as e:
                raise ModbusException(f'exception in Pymodbus library while writing register {address} with {val_str}: {e}',
                                      source=f'modbus:{name}')

    async def write_register(self,
        client_name: str,
        address: int,
        values: list[int],
        no_response_expected: bool = False,
        device_id: int = 3,
    ):
        if not client_name in self._clients:
            raise ConfigException(f'client name {client_name} not configured', source=f'modbus:{client_name}')

        client = self._clients[client_name]
        if client is None:
            return

        val_str = '[' + ','.join(str(v) for v in values) + ']'

        try:
            await client.write_registers(address, values, device_id=device_id, no_response_expected=no_response_expected)
            self.log.debug(f'[modbus:{client_name}]: write register {address} <- {val_str}')
        except PymodbusException as e:
            raise ModbusException(f'exception in Pymodbus library while writing register {address} with {val_str}: {e}',
                                  source=f'modbus:{client_name}')

    async def read_register(self,
        client_name: str,
        address: int,
        dtype: str,
        device_id: int = 3,
        sma_format: str | dict[int, str] | None = None,
        force_holding_register: bool = False,
        word_count: int = 0
    ) -> Any:
        '''
        Read a holding or input register using the named client connected to client_name
        The following logic is used to determine whether the register is a holding or input register:

        3x = Input Register = 30001-39999
        4x = Holding Register = 40001-49999

        If the force_holding_register parameter is True, then Modbus function 0x03 (read holding reg) is forced
        If a positive word_count is specified (eg. for the STRING data type) then that many 16 bit words are read and
        decoded.
        '''
        client = self._clients.get(client_name)
        if client is None:
            return 'dummy' if dtype == 'STRING' else 1.2345  # dummy value

        try:
            cnt = word_count if word_count > 0 else self._dtype_to_word_count(dtype)
            self.log.debug(f'[modbus:{client_name}]: trying to read register {address} (count: {cnt})')

            resp: Optional[ModbusPDU] = None
            if str(address)[0] == '4' or force_holding_register:
                resp = await client.read_holding_registers(address, count=cnt, device_id=device_id)
            elif str(address)[0] == '3':
                resp = await client.read_input_registers(address, count=cnt, device_id=device_id)
            else:
                raise ProgrammingError(f'this method only supports reading input and holding registers',
                                       source=f'modbus:{client_name}')

            if resp.isError():
                code = getattr(resp, 'exception_code', None)
                if code:
                    exc_descr = _modbus_exception_codes.get(resp.exception_code, '<unknown exception>')
                    raise ModbusException(f'error while reading register {address}: ({code}) {exc_descr}',
                                          source=f'modbus:{client_name}')

            value = self._decode_response(client_name, address, dtype, resp, sma_format=sma_format)
            self.log.debug(f'[modbus:{client_name}]: read register {address} -> {value}')
            return value

        except PymodbusException as e:
            raise ModbusException(f'exception in Pymodbus library while reading register {address}: {e}',
                                  source=f'modbus:{client_name}')

    async def read_register_seq(self,
        client_name: str,
        addr: list[tuple[int, str, str]],
        device_id: int = 3,
        force_holding_register: bool = False,
    ) -> list[Any]:
        '''
        Perform sequential reads on a holding or input register using the client connected to client name
        The addr argument must be a list of 3-tuples, each specifying in order:
            - modbus address
            - data type (with optional word count suffixed after a colon: eg. 'STRING:5' )
            - SMA format
        '''
        assert isinstance(addr, list)

        ret = []
        for address, dtype, sma_format in addr:
            if ':' in dtype:
                dtype, word_count_str = dtype.split(':', maxsplit=1)
                ret.append(await self.read_register(
                    client_name, address, dtype,
                    device_id=device_id,
                    sma_format=sma_format,
                    force_holding_register=force_holding_register,
                    word_count=int(word_count_str),
                ))

            else: # no word count
                ret.append(await self.read_register(
                    client_name, address, dtype,
                    device_id=device_id,
                    sma_format=sma_format,
                    force_holding_register=force_holding_register,
                ))

        return ret

    def _parse_batch_fields(self,
        addr: list[tuple[int, str, str]],
        force_holding_register: bool,
        client_name: str,
    ) -> list[_BatchField]:
        '''Work out, per requested value, how many registers it occupies and whether it lives in a holding or
        an input register - the same rules read_register applies, applied up front so the addresses can be
        grouped before anything is sent.
        '''
        fields = []
        for result_index, (address, dtype, sma_format) in enumerate(addr):
            words = 0
            if ':' in dtype:
                dtype, word_count_str = dtype.split(':', maxsplit=1)
                words = int(word_count_str)
            if words <= 0:
                words = self._dtype_to_word_count(dtype)

            if str(address)[0] == '4' or force_holding_register:
                holding = True
            elif str(address)[0] == '3':
                holding = False
            else:
                raise ProgrammingError(f'this method only supports reading input and holding registers',
                                       source=f'modbus:{client_name}')

            fields.append(_BatchField(result_index, address, dtype, sma_format, words, holding))

        return fields

    def _group_batch_fields(self,
        fields: list[_BatchField],
        max_registers: int,
        max_gap: int,
        client_name: str,
    ) -> list[list[_BatchField]]:
        '''Divide the requested values into the groups that can each be fetched in one request: holding and
        input registers never share a request, a group spans at most max_registers, and - when max_gap is set
        - it does not bridge a hole bigger than that. The gap limit is there for devices that answer a span
        covering registers they do not map with an error rather than with padding.
        '''
        groups: list[list[_BatchField]] = []

        for holding in (True, False):
            subset = sorted((f for f in fields if f.holding == holding), key=lambda f: f.address)
            current: list[_BatchField] = []

            for field in subset:
                if field.words > max_registers:
                    raise ProgrammingError(f'register {field.address} needs {field.words} registers, more than '
                                           f'the {max_registers} a single request may hold',
                                           source=f'modbus:{client_name}')

                if current:
                    start = current[0].address
                    end = max(f.address + f.words for f in current)  # one past the last register held so far
                    fits = field.address + field.words - start <= max_registers
                    close_enough = max_gap <= 0 or field.address - end <= max_gap
                    if fits and close_enough:
                        current.append(field)
                        continue

                    groups.append(current)
                    current = []

                current.append(field)

            if current:
                groups.append(current)

        return groups

    async def read_register_batch(self,
        client_name: str,
        addr: list[tuple[int, str, str]],
        device_id: int = 3,
        force_holding_register: bool = False,
        max_registers: int = 125,
        max_gap: int = 0,
        fallback_to_single: bool = True,
    ) -> list[Any]:
        '''Read several registers in as few Modbus requests as their addresses allow.

        Takes and returns what read_register_seq does: the same list of (address, dtype, sma_format) 3-tuples,
        with an optional word count after a colon ('STRING:5'), and the values in the order they were asked
        for. The difference is underneath - rather than one request per address, addresses close together are
        fetched in one request and each value is decoded out of the part of the response it landed in. Reading
        a register nobody asked for costs nothing; it is the round trip that costs, and an SMA device has only
        so many of those to give.

        max_registers caps how wide one request may be (the Modbus limit is 125). max_gap caps the hole it may
        bridge, 0 meaning the span is the only limit: raise it off 0 for a device that refuses a span covering
        registers it does not map. With fallback_to_single a group that fails is retried one address at a
        time, so a device that turns out to be fussy still gets read - the log then says which group it was.
        '''
        assert isinstance(addr, list)
        if len(addr) == 0:
            return []

        client = self._clients.get(client_name)
        if client is None:  # dummy client
            return ['dummy' if dtype.split(':')[0] == 'STRING' else 1.2345 for _, dtype, _ in addr]

        fields = self._parse_batch_fields(addr, force_holding_register, client_name)
        ret: list[Any] = [None] * len(addr)

        for group in self._group_batch_fields(fields, max_registers, max_gap, client_name):
            start = group[0].address
            count = max(f.address + f.words for f in group) - start
            self.log.debug(f'[modbus:{client_name}]: reading {len(group)} value(s) from '
                           f'{start}..{start + count - 1} ({count} registers) in one request')

            try:
                await self._read_batch_group(client_name, client, group, start, count, device_id, ret)

            except Exception as e:
                if not fallback_to_single:
                    raise

                # the device would not serve this span in one go: fall back to what always worked, and say so,
                # since a max_gap on this driver would avoid paying for the failed request every cycle
                self.log.error(f'[modbus:{client_name}]: reading {start}..{start + count - 1} in one request '
                               f'failed ({type(e).__name__}: {e}), falling back to one request per register')
                for field in group:
                    ret[field.result_index] = await self.read_register(
                        client_name, field.address, field.dtype,
                        device_id=device_id,
                        sma_format=field.sma_format,
                        force_holding_register=force_holding_register,
                        word_count=field.words,
                    )

        return ret

    async def _read_batch_group(self,
        client_name: str,
        client: MBClient,
        group: list[_BatchField],
        start: int,
        count: int,
        device_id: int,
        ret: list[Any],
    ) -> None:
        '''Fetch one group in a single request and decode every value out of the response.'''
        if group[0].holding:
            resp = await client.read_holding_registers(start, count=count, device_id=device_id)
        else:
            resp = await client.read_input_registers(start, count=count, device_id=device_id)

        if resp.isError():
            code = getattr(resp, 'exception_code', None)
            exc_descr = _modbus_exception_codes.get(code, '<unknown exception>') if code else '<no exception code>'
            raise ModbusException(f'error while reading registers {start}..{start + count - 1}: ({code}) {exc_descr}',
                                  source=f'modbus:{client_name}')

        registers = list(resp.registers)
        if len(registers) < count:
            raise ModbusException(f'asked for {count} registers from {start} but got {len(registers)}',
                                  source=f'modbus:{client_name}')

        for field in group:
            offset = field.address - start
            value_slice = _RegisterSlice(registers[offset:offset + field.words])
            ret[field.result_index] = self._decode_response(client_name, field.address, field.dtype,
                                                            value_slice, sma_format=field.sma_format)  # type: ignore
            self.log.debug(f'[modbus:{client_name}]: read register {field.address} -> {ret[field.result_index]}')

    async def _read_registers(self,
        client_name: str,
        address: int,
        dtype: str,
        result_dict: dict[str, Any],
        device_id: int = 3,
        sma_format: str | dict[int, str] | None = None,
        force_holding_register: bool = False,
        word_count: int = 0
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
            cnt = word_count if word_count > 0 else self._dtype_to_word_count(dtype)
            self.log.debug(f'[modbus:{client_name}]: trying to read register {address} (count: {cnt})')

            reg_digit = str(address)[0]
            if reg_digit == '4' or force_holding_register:
                resp = await client.read_holding_registers(address, count=cnt, device_id=device_id)
            elif reg_digit == '3':
                resp = await client.read_input_registers(address, count=cnt, device_id=device_id)
            else:
                raise ProgrammingError(f'this method only supports reading input and holding registers ({address})', source=f'modbus:{client_name}')

            if resp.isError():
                code = getattr(resp, 'exception_code', None)
                if code:
                    exc_descr = _modbus_exception_codes.get(resp.exception_code, '<unknown exception>')
                    raise ModbusException(f'error while reading register {address}: ({code}) {exc_descr}', source=f'modbus:{client_name}')
                else:
                    raise ModbusException(f'error while reading register {address}: (code absent) {resp}', source=f'modbus:{client_name}')

            value = self._decode_response(client_name, address, dtype, resp, sma_format=sma_format)
            result_dict[client_name] = value
            self.log.debug(f'[modbus:{client_name}]: read register {address} -> {value}')

        except PymodbusException as e:
            raise ModbusException(f'exception in Pymodbus library while reading register {address}: {e}', source=f'modbus:{client_name}')

    async def read_registers_parallel(self,
        address: int,
        dtype: str,
        device_id: int = 3,
        sma_format: str | dict[int, str] | None = None,
        raise_exceptions: bool = True,
        force_holding_register: bool = False,
        word_count: int = 0
    ) -> dict[str, Any]:
        '''Perform a parallel register read operation across all clients'''
        ret = {}  # collect results here

        tasks = []
        task_names = []
        for name, client in self._clients.items():
            if client is None:
                ret[name] = "dummy" if dtype == 'STRING' else 1.2345  # dummy value
                continue
            tasks.append(self._read_registers(
                name, address, dtype, ret,
                device_id=device_id,
                sma_format=sma_format,
                force_holding_register=force_holding_register,
                word_count=word_count,
            ))
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
        elif dtype == 'U32-STATUS':
            return 2
        elif dtype == 'S32':
            return 2
        elif dtype == 'U64':
            return 4
        elif dtype == 'S64':
            return 4
        elif dtype == 'FLOAT32':
            return 2
        elif dtype == 'FLOAT64':
            return 4
        elif dtype == 'STRING':
            raise ProgrammingError(f'no word_count specified for the STRING data type', source='modbus')

        raise ProgrammingError(f'unrecognized Modbus datatype: {dtype}', source='modbus')

    def _decode_response(self,
        client_name: str,
        address: int,
        dtype: str,
        resp: ModbusPDU,
        sma_format: str | dict[int, str] | None = None,
    ) -> Optional[int | float | str | list[bool] | list[int] | list[float]]:
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
        elif dtype == 'U32-STATUS':
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.UINT32, 'big')
        elif dtype == 'S32':
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.INT32, 'big')
        elif dtype == 'U64':
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.UINT64, 'big')
        elif dtype == 'FLOAT32':
            # The Alfen modbus docs claim the 32-bit values are mixed-Endian: "the 16-bit words are big Endian
            # (high byte first), the 32-bit words are little Endian (low word first)". The charging station does
            # not do this: it sends plain big Endian, low word last, like every other value here. Reading the L1
            # voltage (register 306) gave registers [0x435B, 0x2E14], which is 219.18 V read as big (a plausible
            # phase voltage) and 3.4e-11 read as little. The docs are wrong about the register offset in the same
            # way, see AlfenEvePro._read
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.FLOAT32, 'big')
        elif dtype == 'FLOAT64':
            value = MBClient.convert_from_registers(resp.registers, MBClient.DATATYPE.FLOAT64, 'big')
        elif dtype == 'STRING': # Alfen
            value = self._decode_string(resp.registers)
        else:
            raise ProgrammingError(f'unknown modbus data type {dtype}', source='modbus')

        if value_is_nan(value, dtype):
            self.log.info(f'[modbus:{client_name}]: decoded modbus response {value} into NaN for register {address}')
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

        self.log.debug(f"[modbus:{client_name}]: decoded response '{resp}' into {value} for register {address}")
        return value

    def _decode_string(self, registers: list[int]) -> Optional[str]:
        '''Decode an Alfen string block: each register holds two ASCII chars, high byte first. The string is
        terminated by a zero byte and the field is zero-padded to its fixed width. A field the charging station
        cannot supply is filled with 0xFFFF, which becomes None (our NaN).
        '''
        raw = b''.join(r.to_bytes(2, 'big') for r in registers)
        if all(b == 0xFF for b in raw):
            return None
        return raw.split(b'\x00', 1)[0].decode('ascii', errors='replace').strip()
