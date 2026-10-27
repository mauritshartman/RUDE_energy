'''Day-ahead electricity prices from Enever.

Enever needs an API token, which carries a monthly request budget: every fetch spends two requests, one for
today and one for tomorrow. Spending that budget carelessly is what left a month without dynamic scheduling
in issue #43, so the fetch loop in price.py keeps its retries short and gives up at once on a token problem.

Prices are already quoted in EUR/kWh, which is what the rest of the add-on works in.
'''
from datetime import datetime as dt
from zoneinfo import ZoneInfo

import aiohttp

from common import Logger
from .base import BasePriceSource, PriceSourceAuthError


ENEVER_TODAY =      'https://enever.nl/apiv3/stroomprijs_vandaag.php?token={TOKEN}&price=prijs'
ENEVER_TOMORROW =   'https://enever.nl/apiv3/stroomprijs_morgen.php?token={TOKEN}&price=prijs'

ENEVER_TIME_FMT = '%Y-%m-%dT%H:%M:%S%z'  # the 'datum' field of a price entry


class EneverPrices(BasePriceSource):

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

    @property
    def today_url(self) -> str:
        return self._url(ENEVER_TODAY)

    @property
    def tomorrow_url(self) -> str:
        return self._url(ENEVER_TOMORROW)

    def _url(self, template: str) -> str:
        if self.token is None or len(self.token) == 0:
            raise PriceSourceAuthError('no Enever API token set')
        return template.format(TOKEN=self.token) + f'&resolution={self.resolution}'

    async def fetch(self) -> dict[dt, float]:
        '''Fetch today's prices and, when they have been published, tomorrow's. Enever serves a day per
        endpoint, so this spends two requests. An empty data list for tomorrow means it is not published yet,
        which is not an error: what came back for today is returned on its own.
        '''
        prices: dict[dt, float] = {}

        async with aiohttp.ClientSession() as session:
            self.log.debug(f'fetching Enever prices for today using {self.today_url}')
            async with session.get(self.today_url) as resp:
                parsed = await resp.json()
                if not isinstance(parsed['data'], list):
                    # Enever answers a rejected token with a message in place of the data list
                    raise PriceSourceAuthError(f'no price data returned, check API token validity: {parsed["data"]}')
                self._collect(parsed['data'], prices)

            self.log.debug(f'fetching Enever prices for tomorrow: {self.tomorrow_url}')
            async with session.get(self.tomorrow_url) as resp:
                parsed = await resp.json()
                if len(parsed['data']) == 0:
                    self.log.debug('Enever has no prices for tomorrow yet')
                else:
                    self._collect(parsed['data'], prices)

        return prices

    def _collect(self, entries: list, prices: dict[dt, float]) -> None:
        for p in entries:
            ts = dt.strptime(p['datum'], ENEVER_TIME_FMT).astimezone(self.tz)  # ensure configured timezone
            prices[ts] = float(p['prijs'])
