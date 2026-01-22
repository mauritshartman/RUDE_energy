# LOGGER.PY
#
# Class Logger the is general Blocktraders logger and currently support logging to screen, file and SMS.
# Supported loglevels: DEBUG, INFO, ERROR, FATAL (and OFF)
#
import enum
import os
import json
from datetime import date, datetime as dt, timedelta
from typing import Optional, Union
from pathlib import Path
from aiohttp import web

from singleton import Singleton


class ConfigurationException(Exception):
    """Exception raised due to configuration issues."""

    pass


PREFIX_LENGTH = 22


class LogLevel(enum.IntEnum):
    DEBUG = 500
    NOTE = 450
    INFO = 400
    ERROR = 200
    FATAL = 100
    OFF = 0

_levelToName = {x.value: x.name for x in LogLevel}
_nameToLevel = {x.name: x.value for x in LogLevel}


# noinspection PyPep8Naming
def getLevelName(level: Union[str, int]):
    result = _levelToName.get(level)
    if result is not None:
        return result
    result = _nameToLevel.get(level)
    if result is not None:
        return result
    return f"Level {level}"


class Logger(metaclass=Singleton):
    ROTATE_FRACTION = 1000

    def __init__(
        self,
        message_prefix: Optional[str] = None,
        loglevel: LogLevel = LogLevel.INFO,
        filedir: Optional[Union[Path, str]] = None,
        rotate: Optional[int] = None,
        suffix: Optional[str] = None,
    ):
        self.setup(
            message_prefix=message_prefix,
            loglevel=loglevel,
            filedir=filedir,
            rotate=rotate,
            suffix=suffix,
        )

    def setup(
        self,
        message_prefix: Optional[str] = None,
        loglevel: LogLevel = LogLevel.INFO,
        filedir: Optional[str] = None,
        rotate: Optional[int] = None,
        suffix: Optional[str] = None,
    ):
        """Rules for the logdir:
        - If it starts with ~ expand to the user directory
        - If it starts with / use as full path
        - Otherwise expand cwd
        """
        if loglevel is not None and not isinstance(loglevel, LogLevel):
            raise ConfigurationException(f"Invalid screen loglevel {loglevel}")

        # Loglevels
        self.loglevel = loglevel
        if self.loglevel:
            if filedir is None:
                raise ConfigurationException("Filedir is required when loglevel is not None")

            filedir = str(filedir)
            if filedir.startswith("~"):
                self.filedir = os.path.expanduser(filedir)
            elif filedir.startswith("/"):
                self.filedir = filedir
            else:
                self.filedir = os.path.join(os.getcwd(), filedir)

            if rotate is not None:
                if not isinstance(rotate, (float, int)):
                    raise ConfigurationException("Rotate needs to be float or int")

            self._rotate_delay = rotate

        # optional suffix to apply to filenames:
        self.suffix = "" if suffix is None else suffix
        if message_prefix is None:
            self._message_prefix = ""
        else:
            self._message_prefix = f"{message_prefix:<5}"[:5]

        # Only rotate every now and then so count number of logs
        self._num_logs = 0

    def set_loglevel(self, loglevel: LogLevel):
        self.loglevel = loglevel

    def __call__(self, *msg: str):
        return self.info(*msg)

    def debug(self, *msg: str):
        self._log(*msg, loglevel=LogLevel.DEBUG)

    def note(self, *msg: str):
        self._log(*msg, loglevel=LogLevel.NOTE)

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
            m = str(m)
            combined_msg += str(m)
            combined_msg += " "
        combined_msg = combined_msg[:-1]

        split_msg = combined_msg.split("\n")

        parsed_msg = ""
        for message in split_msg:
            parsed_msg += f"{dt.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} | {loglevel.name:<5} | {self._message_prefix} {message}\n"
        parsed_msg = parsed_msg[:-1]

        self._log_to_file(parsed_msg)
        print(parsed_msg)

    def _today_string(self) -> str:
        """Return a folder based on todays date"""
        today = date.today()
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
        try:
            parsed = await req.json()
            if (
                not isinstance(parsed, dict) or 'date' not in parsed
            ):
                raise Exception(f'invalid log request value: {parsed}')
            ts = dt.strptime(parsed['date'], '%Y-%m-%d')
            logfile = self.get_log(ts)
            if logfile is None:
                return web.Response(text='logfile not present')
            else:
                return web.Response(text=logfile)

        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({'status': 'error', 'msg': str(e)}))

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
        now = dt.now()
        today = dt(year=now.year, month=now.month, day=now.day)

        for log_file in log_files:
            try:
                log_date = dt.strptime(log_file[:10], "%Y-%m-%d")
                age = today - log_date
                if age > delta:
                    to_delete = os.path.join(self.filedir, log_file)
                    self.debug(f"Deleting old log directory {to_delete}")
                    os.remove(to_delete)

            except ValueError as e:
                self.error(f"Cannot parse directory to date: {self.filedir}: {str(e)}")
