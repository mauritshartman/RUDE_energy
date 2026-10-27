'''Day-ahead electricity prices from the ENTSO-E Transparency Platform, as an alternative to Enever.

The API needs a free security token: register at https://transparency.entsoe.eu and then request API access by
mailing transparency@entsoe.eu with 'Restful API access' as the subject. Unlike Enever there is no monthly
request budget, the limit is on requests per minute, and a single request covers both today and tomorrow.

Prices are published per bidding zone in EUR/MWh and are converted here to the EUR/kWh the rest of the add-on
works in. The result of fetch() has the same shape as the Enever fetch in price.py: timezone aware timestamps
in the configured timezone, at the configured resolution.
'''
from datetime import datetime as dt, date, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import aiohttp

from common import Logger
from .base import BasePriceSource, PriceSourceAuthError


ENTSOE_API = 'https://web-api.tp.entsoe.eu/api'
ENTSOE_TIME_FMT = '%Y%m%d%H%M'  # periodStart / periodEnd, always expressed in UTC

# EIC code of the Dutch bidding zone, which a day-ahead price query passes as both in_Domain and out_Domain.
# The add-on is built around a Dutch installation (Enever prices, the Enever API, a three phase connection
# with a Dutch main fuse), so the zone is fixed rather than configurable.
NL_BIDDING_ZONE = '10YNL----------L'

# A Period states its own resolution, which need not match the resolution the add-on is configured for
_RESOLUTION_MINUTES = { 'PT60M': 60, 'PT30M': 30, 'PT15M': 15 }


def _tag(element) -> str:
    '''Local name of an element, dropping the XML namespace'''
    return element.tag.rsplit('}', 1)[-1]


def _find(element, name: str):
    for child in element:
        if _tag(child) == name:
            return child
    return None


def _text(element, name: str) -> Optional[str]:
    child = _find(element, name)
    return None if child is None or child.text is None else child.text.strip()


class EntsoePrices(BasePriceSource):

    def __init__(self,
        token: str,
        tz: ZoneInfo,
        resolution: int,
        log: Logger,
    ) -> None:
        self.token = token
        self.tz = tz
        self.resolution = resolution  # minutes: the resolution the rest of the add-on works in
        self.log = log

    def url(self, period_start: dt, period_end: dt) -> str:
        '''URL for a day-ahead price query (documentType A44) over the given period. Both moments are converted
        to UTC, which is the only thing the API accepts.
        '''
        if self.token is None or len(self.token) == 0:
            raise PriceSourceAuthError('no ENTSO-E security token set')

        return ENTSOE_API + '?' + urlencode({
            'securityToken': self.token,
            'documentType': 'A44',             # price document: day-ahead auction
            'in_Domain': NL_BIDDING_ZONE,    # a price query uses the same zone on both sides
            'out_Domain': NL_BIDDING_ZONE,
            'periodStart': period_start.astimezone(timezone.utc).strftime(ENTSOE_TIME_FMT),
            'periodEnd': period_end.astimezone(timezone.utc).strftime(ENTSOE_TIME_FMT),
        })

    async def fetch(self, day: Optional[date] = None, days: int = 2) -> dict[dt, float]:
        '''Fetch the day-ahead prices covering `days` days from midnight (local time) of `day`, today by
        default. One request covers today and tomorrow, where Enever needs one call per day.

        Returns a possibly empty dict when the requested days are not published yet: the platform leaves out
        what it does not have rather than reporting an error, and only answers with an acknowledgement when
        the whole window is empty.
        '''
        day = day or dt.now(self.tz).date()
        start = dt(day.year, day.month, day.day, tzinfo=self.tz)
        end = start + timedelta(days=days)

        async with aiohttp.ClientSession() as session:
            self.log.debug(f'fetching ENTSO-E day-ahead prices (NL): {start} - {end}')
            async with session.get(self.url(start, end)) as resp:
                body = await resp.text()
                if resp.status == 401:
                    raise PriceSourceAuthError(f'ENTSO-E refused the security token: {self._acknowledgement_reason(body)}')
                if resp.status != 200:
                    raise Exception(f'ENTSO-E returned HTTP {resp.status}: {self._acknowledgement_reason(body)}')

        return self.parse(body)

    def _acknowledgement_reason(self, body: str) -> str:
        '''The reason an acknowledgement document gives, eg. '(999) Authentication failed.' for a bad token'''
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return body[:200]

        reason = _find(root, 'Reason')
        if reason is None:
            return body[:200]
        return f'({_text(reason, "code")}) {_text(reason, "text")}'

    def parse(self, body: str) -> dict[dt, float]:
        '''Turn a Publication_MarketDocument into { timestamp: EUR/kWh }, the timestamps being timezone aware
        in the configured timezone and spaced at the configured resolution.

        Four things the format demands that are easy to get wrong:
        - prices are quoted in EUR/MWh, so they are divided by 1000
        - a document holds a TimeSeries per published day, each with its own period and resolution
        - a Period states a resolution of its own (PT60M, PT30M or PT15M) which need not match ours, so a
          coarser price is repeated across our slots and finer ones are averaged into them
        - with curveType A03 the points are sparse: a position that is absent repeats the price of the last
          position present, through to the end of the period
        '''
        root = ET.fromstring(body)
        if _tag(root) == 'Acknowledgement_MarketDocument':
            # no price data at all for the requested window, eg. a day that is not published yet
            raise Exception(f'ENTSO-E returned no price data: {self._acknowledgement_reason(body)}')

        # collected per slot of our own resolution, then averaged: a finer period contributes several prices
        # to the same slot, a coarser one the same price to each of the slots it covers
        buckets: dict[dt, list[float]] = {}
        for series in root:
            if _tag(series) != 'TimeSeries':
                continue

            unit = _text(series, 'price_Measure_Unit.name') or 'MWH'
            divisor = 1000.0 if unit.upper() == 'MWH' else 1.0  # EUR/MWh -> EUR/kWh

            for period in series:
                if _tag(period) != 'Period':
                    continue
                self._parse_period(period, divisor, buckets)

        return { ts: sum(values) / len(values) for ts, values in buckets.items() }

    def _parse_period(self, period, divisor: float, buckets: dict[dt, list[float]]) -> None:
        interval = _find(period, 'timeInterval')
        resolution = _text(period, 'resolution')
        if interval is None or resolution not in _RESOLUTION_MINUTES:
            self.log.error(f'ENTSO-E: skipping price period with unsupported resolution {resolution}')
            return

        # The arithmetic stays in UTC and only the result is converted to local time. Adding a timedelta to a
        # timezone aware local datetime is wall clock arithmetic, which silently skips or repeats an hour on
        # the two days a year the clocks change - exactly the days a price schedule still has to line up.
        start = dt.fromisoformat(str(_text(interval, 'start')).replace('Z', '+00:00')).astimezone(timezone.utc)
        end = dt.fromisoformat(str(_text(interval, 'end')).replace('Z', '+00:00')).astimezone(timezone.utc)
        step = timedelta(minutes=_RESOLUTION_MINUTES[resolution])
        slots = int((end - start) / step)

        points: dict[int, float] = {}  # position (1 based) -> price
        for point in period:
            if _tag(point) != 'Point':
                continue
            position, amount = _text(point, 'position'), _text(point, 'price.amount')
            if position is not None and amount is not None:
                points[int(position)] = float(amount) / divisor

        if not points:
            self.log.error(f'ENTSO-E: price period {start} - {end} holds no prices')
            return

        # walk every slot of the period: a position that is missing repeats the previous price (curveType A03)
        last_price = points[min(points)]
        for position in range(1, slots + 1):
            last_price = points.get(position, last_price)
            self._store(start + (position - 1) * step, step, last_price, buckets)

    def _store(self, slot_start: dt, step: timedelta, price: float, buckets: dict[dt, list[float]]) -> None:
        '''Record a price against each slot of our own resolution that it covers. slot_start is in UTC, the
        keys are in the configured timezone: that is what the rest of the add-on works in, see
        PriceManager.normalize_to_resolution.
        '''
        own_step = timedelta(minutes=self.resolution)

        if step <= own_step:  # finer than ours: fold into the slot it falls in, the caller averages
            local = slot_start.astimezone(self.tz)
            minute = local.minute // self.resolution * self.resolution
            buckets.setdefault(local.replace(minute=minute, second=0, microsecond=0), []).append(price)
            return

        ts = slot_start  # coarser than ours: the same price for every slot it covers
        while ts < slot_start + step:
            buckets.setdefault(ts.astimezone(self.tz), []).append(price)
            ts += own_step
