from datetime import datetime as dt, timedelta, timezone
from pathlib import Path
import asyncio
import json
from typing import Optional, Union

import aiohttp

from config import DoeMaarWattConfig
from logger import Logger
from night_price_predictor import init_night_price_predictor, predict_night_price
from time_functions import datetimerange


ENEVER_TODAY =      'https://enever.nl/apiv3/stroomprijs_vandaag.php?token={TOKEN}&price=prijs'
ENEVER_TOMORROW =   'https://enever.nl/apiv3/stroomprijs_morgen.php?token={TOKEN}&price=prijs'

MAX_ATTEMPTS = 5

PRICE_PATH = Path('/data/prices.json')
PRICE_PATH = Path('prices.json')
TIME_FMT = '%Y-%m-%dT%H:%M:%S%z'


class PriceManager:
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        self.log = log

        self.enever_token = cfg.get_mode_dynamic_config()['api_token']

        self.tz = timezone(timedelta(hours=cfg.timezone_offset))

        self.resolution: int = int(cfg.get_mode_dynamic_config()['resolution'])
        self.price_update_time = cfg.get_mode_dynamic_config()['price_update_time']

        self.prices_ts: Optional[dt] = None
        self.prices: dict[dt, float] = {}
        if PRICE_PATH.exists():
            self.load_prices()

        init_night_price_predictor(log)

    @property
    def enever_today_url(self) -> str:
        if self.enever_token is None or len(self.enever_token) == 0:
            raise ValueError(f'no Enever API token set')
        return ENEVER_TODAY.format(TOKEN=self.enever_token) + f'&resolution={self.resolution}'

    @property
    def enever_tomorrow_url(self) -> str:
        if self.enever_token is None or len(self.enever_token) == 0:
            raise ValueError(f'no Enever API token set')
        return ENEVER_TOMORROW.format(TOKEN=self.enever_token) + f'&resolution={self.resolution}'

    def to_dict(self) -> dict:
        return {
            'update_ts': self.prices_ts.strftime(TIME_FMT) if self.prices_ts else None,
            'prices': {k.strftime(TIME_FMT): v for k, v in self.prices.items()}
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def from_json(self, raw: Union[bytes, str]) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')

        parsed = json.loads(raw)
        self.prices_ts = dt.strptime(parsed['update_ts'], TIME_FMT) if parsed['update_ts'] else None
        self.prices = { dt.strptime(k, TIME_FMT): v for k, v in parsed['prices'].items()}

    def save_prices(self) -> None:
        '''Save the current prices to a json file'''
        with PRICE_PATH.open('w') as f:
            f.write(self.to_json())

    def load_prices(self) -> None:
        '''Load the current prices from a json file'''
        with PRICE_PATH.open('r') as f:
            raw = f.read()
            self.from_json(raw)
            self.log.debug(f'loaded prices from {PRICE_PATH}')

    async def fetch_prices(self) -> None:
        attempt_no = 1
        while attempt_no < MAX_ATTEMPTS:
            if attempt_no > 1:
                await asyncio.sleep(10 * 2**attempt_no) # exponential backoff

            try:
                new_prices = {}

                async with aiohttp.ClientSession() as session:
                    self.log.debug(f'fetching prices for today using {self.enever_today_url}')
                    async with session.get(self.enever_today_url) as resp:
                        parsed = await resp.json()
                        if not isinstance(parsed['data'], list):
                            raise Exception(f'no price data returned, check API token validity: {parsed["data"]}')
                        for p in parsed['data']:
                            ts = dt.strptime(p['datum'], TIME_FMT).astimezone(self.tz)  # ensure configured timezone
                            new_prices[ts] = float(p['prijs'])

                    self.log.debug(f'fetching prices for tomorrow: {self.enever_tomorrow_url}')
                    async with session.get(self.enever_tomorrow_url) as resp:
                        parsed = await resp.json()
                        if len(parsed['data']) == 0:  # empty data list indicates data for tomorrow is not available yet
                            self.log.debug(f'tomorrow\'s data not yet available')
                        else:
                            for p in parsed['data']:
                                ts = dt.strptime(p['datum'], TIME_FMT).astimezone(self.tz)  # ensure configured timezone
                                new_prices[ts] = float(p['prijs'])

                try:
                    resolution_str = {15: '15min', 60: '1hour'}.get(self.resolution, '15min')
                    if resolution_str is None:
                        self.log.info(f'night price predictor: unsupported resolution {self.resolution}min, skipping prediction')
                    else:
                        prev_date = max(new_prices).date()
                        prediction_date = prev_date + timedelta(days=1)
                        prev_hourly = self._get_hourly_prices(prev_date)
                        self.log.debug(f'predicting additional prices for {prediction_date} based on prices of {prev_date}')
                        if prev_hourly is not None:
                            night_predictions = predict_night_price(prediction_date, prev_hourly, resolution_str)
                            pred_times = []
                            for pred in night_predictions:
                                h, m = map(int, pred['time'].split(':'))
                                pred_ts = dt(prediction_date.year, prediction_date.month, prediction_date.day, h, m, tzinfo=self.tz)
                                pred_times.append(pred_ts)
                                new_prices[pred_ts] = pred['price']
                            self.log.debug(f'added {len(night_predictions)} predicted night prices for {prediction_date} [{min(pred_times)} - {max(pred_times)}]')
                except Exception as e:
                    self.log.error(f'error predicting night prices: {e}')  # just a log message, no further escalation

                self.prices = new_prices
                self.prices_ts = dt.now(self.tz)
                self.save_prices()
                self.log.info(f'fetched and stored prices for [{min(self.prices)} - {max(self.prices)}]')
                return

            except Exception as e:
                self.log.error(f'error while fetching, parsing or storing prices (attempt #{attempt_no}): {e}')
                attempt_no += 1

        raise Exception(f'unable to fetch prices - exhausted all attempts')
        # TODO send a push message when this happens - preferably through HA

    def _get_hourly_prices(self, target_date) -> Optional[list[float]]:
        '''Extract 24 hourly average prices from self.prices for target_date. Returns None if any hour is missing.'''
        hourly = []
        for hour in range(24):
            hour_start = dt(target_date.year, target_date.month, target_date.day, hour, 0, tzinfo=self.tz)
            hour_end = hour_start + timedelta(hours=1)
            slot_prices = [v for k, v in self.prices.items() if hour_start <= k < hour_end]
            if not slot_prices:
                self.log.info(f'night price predictor: no prices for {target_date} hour {hour}, skipping prediction')
                return None
            hourly.append(sum(slot_prices) / len(slot_prices))
        return hourly

    def get_price(self, st: Optional[dt] = None) -> float:
        if st is None:
            s_ts = dt.now(self.tz)
        else:
            s_ts = st.astimezone(self.tz)

        # check if request time falls within intervals:
        times = list(sorted(self.prices))
        for t1, t2 in zip(times, times[1:]):
            if t1 <= s_ts and s_ts < t2:
                return self.prices[t1]

        # check if it falls within the final interval
        if times[-1] <= s_ts and s_ts < times[-1] + timedelta(minutes=self.resolution):
            return self.prices[times[-1]]

        raise Exception(f'could not get price for {st} (normalized to {s_ts}) in current prices [{min(self.prices)} - {max(self.prices)}]')

    def normalize_to_resolution(self, t: dt) -> dt:
        '''Normalize the given time t to the resolution of this price manager'''
        assert t.tzinfo == self.tz, 'timezones do not match'
        minutes = t.minute // self.resolution * self.resolution  # normalize minutes to resolution
        return dt(t.year, t.month, t.day, t.hour, minutes, tzinfo=self.tz)

    def get_price_range(self, start_from: Optional[dt] = None) -> list[tuple[dt, dt, float]]:
        '''
        Return all the prices in a list representation, where each interval (of resolution minutes length) is returned as a 3-tuple
        (start_dt, end_dt, price). If start_from is given, only intervals which contain start_from or are later are returned.
        '''
        if start_from is None:
            start_from = min(self.prices)
        interval_length = timedelta(minutes=self.resolution)
        price_range_start = self.normalize_to_resolution(start_from)
        price_range_end = self.normalize_to_resolution(max(self.prices)) + interval_length

        ret = []
        times = list(sorted(self.prices))  # not yet normalized
        for iv_start in datetimerange(price_range_start, price_range_end, size=interval_length):
            iv_end = iv_start + interval_length

            # find the newest price timestamp which is older than iv_end:
            try:
                price_key = max(t for t in times if t < iv_end)
                ret.append((iv_start, iv_end, self.prices[price_key]))
            except ValueError as e:  # empty, so likely no starting price
                raise ValueError(f'cannot determine price for time interval [{iv_start}, {iv_end})')

        return ret
