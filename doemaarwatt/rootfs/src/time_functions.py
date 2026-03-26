from datetime import date, datetime, timedelta
from decimal import Decimal as D
from typing import Any, Generator, Tuple, Optional


def daterange(start: date, end: date, size: int = 1) -> Generator[date, None, None]:
    """Create an iterator that yields successive dates that completely fit in the given range [start, end]"""
    assert isinstance(size, int) and size > 0
    assert isinstance(start, date) and isinstance(end, date)

    next_d = start
    while next_d < end:
        yield next_d
        next_d += timedelta(days=size)


def datetimerange(
    start: datetime, end: datetime, size: timedelta = timedelta(days=1)
) -> Generator[datetime, None, None]:
    """Create an iterator that yields successive datetime timestamps that fit in the given range [start, end).
    The default step size is 1 day, but this can be modified"""
    next_d = start
    while next_d < end:
        yield next_d
        next_d += size


def timerange(
    start: datetime,
    end: datetime,
    size: timedelta = timedelta(days=1),
    overlap: timedelta = timedelta(0),
) -> Generator[Tuple[datetime, datetime], None, None]:
    """Yield successive -or- inconsequetive timerange tuples (start, end) of a given size from the given start, end arguments.
    if start is greater then end date, it makes the generator reversible

    Args:
        start (datetime): start date
        end (datetime): end date
        size (timedelta): step size
        overlap (timedelta): when specified the generated tuples overlap in time
    """
    if end > start:
        s = start
        while True:
            if s >= end:
                return

            e = min(s + abs(size), end)
            yield s, e

            s += abs(size) - abs(overlap)

    elif start > end:  # reversible generator
        s = start
        while True:
            if s <= end:
                return

            e = max(s - abs(size), end)
            yield s, e

            s -= abs(size) - abs(overlap)
