# LOGGER.PY
#
# Class Logger the is a general logger and currently support logging to screen and file.
# Supported loglevels: DEBUG, INFO, ERROR, FATAL (and OFF)
#
import enum
import os
import io
import gzip
import json
import asyncio
import zipfile
from datetime import date, datetime as dt, timedelta
from typing import Optional, Union
from pathlib import Path
from zoneinfo import ZoneInfo
from aiohttp import web

from .singleton import Singleton
from .exceptions import ConfigException


PREFIX_LENGTH = 22


class LogLevel(enum.IntEnum):
    DEBUG = 500
    INFO = 400
    ERROR = 200
    FATAL = 100
    OFF = 0

_levelToName = {x.value: x.name for x in LogLevel}
_nameToLevel = {x.name: x.value for x in LogLevel}


# noinspection PyPep8Naming
def getLevelName(level: Union[str, int]):
    result = _levelToName.get(level)  # type: ignore
    if result is not None:
        return result
    result = _nameToLevel.get(level)  # type: ignore
    if result is not None:
        return result
    return f"Level {level}"


class Logger(metaclass=Singleton):
    ROTATE_FRACTION = 1000

    def __init__(self,
        message_prefix: Optional[str] = None,
        loglevel: LogLevel = LogLevel.INFO,
        filedir: Optional[Union[Path, str]] = None,
        rotate: Optional[int] = None,
        suffix: Optional[str] = None,
        tz_name: Optional[str] = None,
    ):
        self.setup(
            message_prefix=message_prefix,
            loglevel=loglevel,
            filedir=filedir,
            rotate=rotate,
            suffix=suffix,
            tz_name=tz_name,
        )

    def setup(self,
        message_prefix: Optional[str] = None,
        loglevel: LogLevel = LogLevel.INFO,
        filedir: Optional[Union[Path, str]] = None,
        rotate: Optional[int] = None,
        suffix: Optional[str] = None,
        tz_name: Optional[str] = None,
    ):
        """Rules for the logdir:
        - If it starts with ~ expand to the user directory
        - If it starts with / use as full path
        - Otherwise expand cwd
        """
        if loglevel is not None and not isinstance(loglevel, LogLevel):
            raise ConfigException(f"invalid screen loglevel {loglevel}", source='logger')

        # timezone
        self.tz = ZoneInfo(tz_name) if tz_name is not None else ZoneInfo('UTC')

        # Loglevels
        self.loglevel = loglevel
        if self.loglevel:
            if filedir is None:
                raise ConfigException("filedir is required when loglevel is not None", source='logger')

            filedir = str(filedir)
            if filedir.startswith("~"):
                self.filedir = os.path.expanduser(filedir)
            elif filedir.startswith("/"):
                self.filedir = filedir
            else:
                self.filedir = os.path.join(os.getcwd(), filedir)

            if rotate is not None:
                if not isinstance(rotate, (float, int)):
                    raise ConfigException("Rotate needs to be float or int", source='logger')

            self._rotate_delay = rotate

        # optional suffix to apply to filenames:
        self.suffix = "" if suffix is None else suffix
        if message_prefix is None:
            self._message_prefix = ""
        else:
            self._message_prefix = f"{message_prefix:<5}"[:5]

        # Only rotate every now and then so count number of logs
        self._num_logs = 0

    def set_timezone(self, tz_name: str):
        self.tz = ZoneInfo(tz_name)
        self.debug(f'setting logging timezone to {self.tz}')

    def set_loglevel(self, loglevel: LogLevel):
        self.loglevel = loglevel

    def __call__(self, *msg: str):
        return self.info(*msg)

    def debug(self, *msg: str):
        self._log(*msg, loglevel=LogLevel.DEBUG)

    def info(self, *msg: str):
        self._log(*msg, loglevel=LogLevel.INFO)

    def error(self, *msg: str):
        self._log(*msg, loglevel=LogLevel.ERROR)

    def fatal(self, *msg: str):
        self._log(*msg, loglevel=LogLevel.FATAL)

    def _log(
        self,
        *msg: str,
        loglevel: LogLevel,
    ):
        assert isinstance(loglevel, LogLevel)
        if loglevel > self.loglevel:
            return

        # Parse message
        combined_msg = ""
        for m in msg:
            combined_msg += str(m)
            combined_msg += " "
        combined_msg = combined_msg[:-1]

        split_msg = combined_msg.split("\n")

        ts = f'{dt.now(self.tz).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}'
        parsed_msg = ""
        for message in split_msg:
            parsed_msg += f"{ts} | {loglevel.name:<5} | {self._message_prefix} {message}\n"
        parsed_msg = parsed_msg[:-1]

        self._log_to_file(parsed_msg)
        print(parsed_msg)

    def _today_string(self) -> str:
        """Return a folder based on todays date"""
        today = dt.now(self.tz).date()
        return f"{today.year}-{today.month:02d}-{today.day:02d}"

    def _filename(self) -> str:
        return self._today_string() + self.suffix + ".log"

    def get_log(self, ts: Union[dt, date]) -> Optional[str]:
        if isinstance(ts, dt) or isinstance(ts, date):
            logfile = f"{ts.year}-{ts.month:02d}-{ts.day:02d}" + self.suffix + '.log'
        filepath = os.path.join(self.filedir, logfile)
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return f.read()

        return None

    async def handle_log(self, req):
        '''POST /api/log with {"date": "YYYY-MM-DD", "offset": <bytes>} - return the log for that date from
        byte `offset` to the end of the file, so the UI can fetch only newly-appended lines instead of the
        whole file on every poll. `offset` defaults to 0 (whole file); an out-of-range offset (e.g. a rotated
        file) also returns the whole file. Response headers X-Log-Start (byte offset the body begins at) and
        X-Log-Size (current total size) let the client decide whether to append or replace, and what offset to
        request next. The body is gzip-compressed when the client accepts it. The file read + compression run
        in a thread executor: both are blocking and this server shares its event loop with the control loop.
        '''
        try:
            parsed = await req.json()
            if (
                not isinstance(parsed, dict) or 'date' not in parsed
            ):
                raise Exception(f'invalid log request value: {parsed}')
            ts = dt.strptime(parsed['date'], '%Y-%m-%d').astimezone(self.tz)
            offset = parsed.get('offset')
            if not isinstance(offset, int) or offset < 0:
                offset = 0
            gzip_it = 'gzip' in (req.headers.get('Accept-Encoding') or '')

            result = await asyncio.get_running_loop().run_in_executor(None, self._read_log_range, ts, offset, gzip_it)
            if result is None:
                # no log file for this date: empty body, size 0
                return web.Response(body=b'', content_type='text/plain', charset='utf-8',
                                    headers={'X-Log-Start': '0', 'X-Log-Size': '0'})

            body, start, size, gzipped = result
            headers = {'X-Log-Start': str(start), 'X-Log-Size': str(size)}
            if gzipped:
                headers['Content-Encoding'] = 'gzip'
            return web.Response(body=body, content_type='text/plain', charset='utf-8', headers=headers)

        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    def _read_log_range(self, ts: Union[dt, date], offset: int, gzip_it: bool):
        '''Read a day's log file from byte `offset` to EOF, optionally gzip-compressing the result. Returns
        (body, start, size, gzipped) where `start` is the byte offset the body begins at (0 - i.e. the whole
        file - when `offset` is out of range, e.g. a rotated file), `size` is the current total file size, and
        `gzipped` says whether `body` is compressed. Returns None if the file does not exist. Blocking (file
        read + compression) - run in a thread executor.'''
        if isinstance(ts, (dt, date)):
            logfile = f"{ts.year}-{ts.month:02d}-{ts.day:02d}" + self.suffix + '.log'
        filepath = os.path.join(self.filedir, logfile)
        if not os.path.exists(filepath):
            return None
        with open(filepath, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = offset if 0 <= offset <= size else 0
            f.seek(start)
            body = f.read()
        if gzip_it:
            body = gzip.compress(body)
        return body, start, size, gzip_it

    async def handle_log_download(self, req):
        '''GET /api/log/download?date=YYYY-MM-DD - serve a day's log file as a downloadable zip attachment.

        Log files can be large, so the file is compressed into a zip and served with a Content-Disposition
        header so the browser saves it. The read + compression is done in a thread executor: both are blocking
        and this web server shares its event loop with the control loop, so doing that work off the loop keeps
        the controller responsive. This is the download path used by the UI (works inside the HA ingress iframe).
        '''
        try:
            date_str = req.query.get('date')
            if not date_str:
                raise Exception('missing "date" query parameter')
            ts = dt.strptime(date_str, '%Y-%m-%d').astimezone(self.tz)  # also validates the format

            # build names from the parsed date (not the raw query string) to avoid header injection
            date_fmt = ts.strftime('%Y-%m-%d')
            log_name = f'doemaarwatt-{date_fmt}.log'   # name of the file inside the zip
            zip_name = f'doemaarwatt-{date_fmt}.zip'   # download filename

            # read the (potentially large) log file and zip it off the event loop
            data = await asyncio.get_running_loop().run_in_executor(None, self._zip_log, ts, log_name)
            if data is None:
                return web.Response(text='logfile not present', status=404)

            return web.Response(
                body=data,
                headers={
                    'Content-Type': 'application/zip',
                    'Content-Disposition': f'attachment; filename="{zip_name}"',
                },
            )

        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

    def _zip_log(self, ts: Union[dt, date], log_name: str) -> Optional[bytes]:
        '''Read the log file for `ts` and return it as an in-memory zip containing a single `log_name` entry,
        or None if the log file does not exist. Blocking (file read + compression); run in a thread executor.'''
        logfile = self.get_log(ts)
        if logfile is None:
            return None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(log_name, logfile)
        return buf.getvalue()

    def _log_to_file(self, msg: str):
        """Save a msg to file"""
        # Make dir
        if not os.path.exists(self.filedir):
            os.makedirs(self.filedir)

        # Write to file
        filepath = os.path.join(self.filedir, self._filename())
        with open(filepath, "a") as f:
            f.write(msg + "\n")

        # Rotate
        if self._rotate_delay is not None:
            if self._num_logs % self.ROTATE_FRACTION == 0:
                self._rotate_files()
            self._num_logs += 1

    def _rotate_files(self) -> None:
        """Delete old folders from the log"""
        assert self._rotate_delay is not None

        log_files = [f for f in os.listdir(self.filedir) if f.endswith(".log")]
        delta = timedelta(days=self._rotate_delay)
        now = dt.now(self.tz)
        today = dt(year=now.year, month=now.month, day=now.day, tzinfo=self.tz)

        for log_file in log_files:
            try:
                log_date = dt.strptime(log_file[:10], "%Y-%m-%d").astimezone(self.tz)
                age = today - log_date
                if age > delta:
                    to_delete = os.path.join(self.filedir, log_file)
                    print(f"deleting old log directory {to_delete}")
                    os.remove(to_delete)

            except ValueError as e:
                print(f"cannot parse directory to date: {self.filedir}: {str(e)}")
