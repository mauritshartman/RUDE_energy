from datetime import datetime as dt, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import asyncio
import json
from typing import Optional, Union

from config import DoeMaarWattConfig, PRICE_SOURCE_ENEVER, PRICE_SOURCE_ENTSOE
from common import Logger, datetimerange
from predictor import init_night_price_predictor, predict_night_price
from .base import BasePriceSource, PriceSourceAuthError
from .enever import EneverPrices
from .entsoe import EntsoePrices

# Attempts per fetch, each of which costs a request (two for Enever, which needs a call per day). Keep this
# small: a source that is down stays down for longer than a retry loop can sensibly wait, and the daily
# price_loop comes back to it anyway. A long loop here burns an API budget rather than solving anything,
# which is what used up a month of Enever tokens in issue #43
MAX_ATTEMPTS = 5

# Shortest time between two fetch attempts made by ensure_prices. The reconnect loop asks on every (re)connect,
# which for a flaky subsystem is every RECONNECT_DELAY seconds, and a source that has nothing to add is no
# more likely to have something a moment later. The daily update in price_loop is not held back by this
MIN_FETCH_INTERVAL = timedelta(minutes=15)

PRICE_PATH = Path('/data/prices.json')
PRICE_PATH = Path('prices.json')
TIME_FMT = '%Y-%m-%dT%H:%M:%S%z'


class PriceManager:
    def __init__(self,
        cfg: DoeMaarWattConfig,
        log: Logger,
    ) -> None:
        self.log = log

        self.tz = ZoneInfo(cfg.timezone)

        self.resolution: int = int(cfg.get_mode_dynamic_config()['resolution'])
        self.price_update_time = cfg.get_mode_dynamic_config()['price_update_time']

        # Where the day-ahead prices come from. Both sources produce the same thing: a mapping of timezone
        # aware timestamps (at self.resolution) to a price in EUR/kWh, which everything below works with
        self.price_source: str = cfg.get_mode_dynamic_config().get('price_source', PRICE_SOURCE_ENEVER)
        self.source: BasePriceSource = self._create_source(cfg, log)

        self._prices_ts: Optional[dt] = None
        self._prices: dict[dt, float] = {}
        self._last_fetch_attempt: Optional[dt] = None  # attempts, not successes: see ensure_prices
        if PRICE_PATH.exists():
            self.load_prices()

        init_night_price_predictor(log)

    @property
    def prices(self) -> dict[dt, float]:
        return self._prices

    @prices.setter
    def prices(self, new_prices: dict[dt, float]):
        self._prices = new_prices
        self._prices_ts = dt.now(self.tz)

    @property
    def prices_ts(self) -> Optional[dt]:
        return self._prices_ts

    @prices_ts.setter
    def prices_ts(self, ts: dt):
        self._prices_ts = ts

    def _create_source(self, cfg: DoeMaarWattConfig, log: Logger) -> BasePriceSource:
        '''Build the price source the configuration asks for. Each needs its own credential, which config.py
        checks is present before a source can be selected.
        '''
        mode_cfg = cfg.get_mode_dynamic_config()
        if self.price_source == PRICE_SOURCE_ENTSOE:
            return EntsoePrices(token=mode_cfg.get('entsoe_token', ''), tz=self.tz,
                                resolution=self.resolution, log=log)
        return EneverPrices(token=mode_cfg.get('api_token', ''), tz=self.tz,
                            resolution=self.resolution, log=log)

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
        self.prices = { dt.strptime(k, TIME_FMT): v for k, v in parsed['prices'].items()}
        if parsed['update_ts']:
            self.prices_ts = dt.strptime(parsed['update_ts'], TIME_FMT)

    def save_prices(self) -> None:
        '''Save the current prices to a json file'''
        with PRICE_PATH.open('w') as f:
            f.write(self.to_json())

    def load_prices(self) -> None:
        '''Load the prices an earlier run cached, unless they are too old to be of any use.

        A cache that does not reach the present cannot price anything that is scheduled now, and keeping it
        makes every lookup fail until the first fetch lands - including the ones behind the status endpoint,
        which then answers the web UI with an error instead of a page. Starting with no prices at all is the
        more honest state: it says 'not known yet' rather than offering prices from another week.
        '''
        with PRICE_PATH.open('r') as f:
            raw = f.read()
            self.from_json(raw)

        now = dt.now(self.tz)
        last_slot_ends = max(self._prices) + timedelta(minutes=self.resolution) if self._prices else None
        if last_slot_ends is None or last_slot_ends <= now:
            self.log.info(f'discarding the prices cached in {PRICE_PATH}: they run to {last_slot_ends} and so '
                          f'do not cover {now} - waiting for the first fetch instead')
            self._prices = {}
            self._prices_ts = None
            return

        self.log.debug(f'loaded prices from {PRICE_PATH} [{min(self._prices)} - {max(self._prices)}]')

    def has_prices_through(self, horizon: dt) -> bool:
        '''True when the prices held cover everything up to horizon, so there is nothing to fetch.'''
        if len(self._prices) == 0:
            return False
        return max(self._prices) + timedelta(minutes=self.resolution) >= horizon

    def price_horizon(self, now: dt) -> dt:
        '''How far the prices have to reach to be as complete as they can be at this moment.

        Tomorrow's prices appear in the course of the afternoon, around the configured price_update_time, so
        before that moment a set that covers today is everything there is to have, and after it a complete set
        runs to the end of tomorrow. Midnight is built from the date rather than by adding a day to now, which
        on the two days the clocks change would land an hour out.
        '''
        def midnight(d) -> dt:
            return dt(d.year, d.month, d.day, tzinfo=self.tz)

        end_of_today = midnight((now + timedelta(days=1)).date())
        h, m = map(int, self.price_update_time.split(':'))
        published = now.replace(hour=h, minute=m, second=0, microsecond=0)

        return end_of_today if now < published else midnight((now + timedelta(days=2)).date())

    async def ensure_prices(self, now: Optional[dt] = None) -> None:
        '''Fetch prices only when the ones already held cannot cover what is needed.

        This is what the reconnect loop asks for. A subsystem that keeps dropping its connection makes that
        loop come round every RECONNECT_DELAY seconds, and fetching prices on each pass is what emptied a
        month of Enever's request budget in issue #43 - while the prices themselves were perfectly fine, it
        being the Modbus connection that was not. Asking the cache first costs nothing in that case.

        A fetch that leaves the horizon uncovered (tomorrow published late, a source that is down) is not
        repeated until MIN_FETCH_INTERVAL has passed, so the reconnect loop cannot turn into a fetch loop.
        '''
        now = now or dt.now(self.tz)

        horizon = self.price_horizon(now)
        if self.has_prices_through(horizon):
            self.log.debug(f'prices cover everything up to {horizon}, so no fetch is needed')
            return

        if self._last_fetch_attempt is not None and now - self._last_fetch_attempt < MIN_FETCH_INTERVAL:
            self.log.debug(f'prices do not reach {horizon}, but the last fetch attempt was at '
                           f'{self._last_fetch_attempt}: waiting at least {MIN_FETCH_INTERVAL} between attempts')
            return

        self.log.info(f'prices do not reach {horizon}, fetching from {self.price_source}')
        self._last_fetch_attempt = now
        await self.fetch_prices(initial=True)

    async def fetch_prices(self, initial=False) -> None:
        '''Fetch the day-ahead prices from the configured source and store them.

        What happens around the fetch is the same whichever source supplies the prices: the coming night is
        predicted from what came back, the result is stored and cached, and a set that does not yet hold
        tomorrow is run on while another attempt is made to complete it.
        '''
        attempt_no = 1
        while attempt_no <= MAX_ATTEMPTS:
            if attempt_no > 1:
                sleep_time = 60 * 10 # 10 minutes
                if attempt_no < 5:
                    sleep_time = 2**(attempt_no + 1) # exponential backoff
                await asyncio.sleep(sleep_time)

            try:
                new_prices = await self.source.fetch()
                if len(new_prices) == 0:
                    raise Exception('no prices returned for today or tomorrow')

                # a source leaves out what it has not published yet, so check whether tomorrow made it in
                tomorrow = (dt.now(self.tz) + timedelta(days=1)).date()
                has_tomorrow = any(ts.date() == tomorrow for ts in new_prices)

                self.extrapolate_prices(new_prices)
                self.prices = new_prices
                self.save_prices()

                if has_tomorrow:
                    self.log.info(f'fetched and stored prices for [{min(self.prices)} - {max(self.prices)}]')
                    return

                # no data for tomorrow yet: run on what we have while we attempt to grab tomorrow's prices
                self.log.info(f'fetched and stored limited price set for [{min(self.prices)} - {max(self.prices)}]')
                if initial:
                    # the initial startup time might be in the morning, so a retry for tomorrow makes no sense
                    return
                raise Exception('tomorrow\'s prices unavailable')

            except PriceSourceAuthError as e:
                # a missing, wrong or not yet activated credential: no number of retries makes that succeed,
                # so give up at once rather than spending requests on a call that cannot work
                self.log.error(f'cannot fetch {self.price_source} prices: {e}')
                raise

            except Exception as e:
                self.log.error(f'error while fetching, parsing or storing {self.price_source} prices '
                               f'(attempt #{attempt_no}): {e}')
                attempt_no += 1

        raise Exception(f'unable to fetch prices - exhausted all attempts')

    def extrapolate_prices(self, prices: dict[dt, float]):
        try:
            resolution_str = {15: '15min', 60: '1hour'}.get(self.resolution, '15min')
            if resolution_str is None:
                self.log.info(f'night price predictor: unsupported resolution {self.resolution}min, skipping prediction')
            else:
                prev_date = max(prices).date()
                prediction_date = prev_date + timedelta(days=1)
                prev_hourly = self._get_hourly_prices(prev_date, prices)
                self.log.debug(f'predicting additional prices for {prediction_date} based on prices of {prev_date}')

                if prev_hourly is not None:
                    night_predictions = predict_night_price(prediction_date, prev_hourly, resolution_str)
                    pred_times = []
                    for pred in night_predictions:
                        h, m = map(int, pred['time'].split(':'))
                        pred_ts = dt(prediction_date.year, prediction_date.month, prediction_date.day, h, m, tzinfo=self.tz)
                        pred_times.append(pred_ts)
                        prices[pred_ts] = pred['price']
                    self.log.debug(f'added {len(night_predictions)} predicted night prices for {prediction_date} [{min(pred_times)} - {max(pred_times)}]')

        except Exception as e:
            self.log.error(f'error predicting night prices: {e}')  # just a log message, no further escalation

    def _get_hourly_prices(self, target_date, prices: dict[dt, float]) -> Optional[list[float]]:
        '''Extract 24 hourly average prices from self.prices for target_date. Returns None if any hour is missing.'''
        hourly = []
        for hour in range(24):
            hour_start = dt(target_date.year, target_date.month, target_date.day, hour, 0, tzinfo=self.tz)
            hour_end = hour_start + timedelta(hours=1)
            slot_prices = [v for k, v in prices.items() if hour_start <= k < hour_end]
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
        prices = self.prices
        if len(prices) == 0:
            raise Exception(f'could not get price for {st} (normalized to {s_ts}): no prices are known yet')

        times = list(sorted(prices))
        for t1, t2 in zip(times, times[1:]):
            if t1 <= s_ts and s_ts < t2:
                return prices[t1]

        # check if it falls within the final interval
        if times[-1] <= s_ts and s_ts < times[-1] + timedelta(minutes=self.resolution):
            return prices[times[-1]]

        raise Exception(f'could not get price for {st} (normalized to {s_ts}) in current prices [{min(prices)} - {max(prices)}]')

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
        prices = self.prices

        if start_from is None:
            start_from = min(prices)
        interval_length = timedelta(minutes=self.resolution)
        price_range_start = self.normalize_to_resolution(start_from)
        price_range_end = self.normalize_to_resolution(max(prices)) + interval_length

        ret = []
        times = list(sorted(prices))  # not yet normalized
        for iv_start in datetimerange(price_range_start, price_range_end, size=interval_length):
            iv_end = iv_start + interval_length

            # find the newest price timestamp which is older than iv_end:
            try:
                price_key = max(t for t in times if t < iv_end)
                ret.append((iv_start, iv_end, prices[price_key]))
            except ValueError as e:  # empty, so likely no starting price
                raise ValueError(f'cannot determine price for time interval [{iv_start}, {iv_end})')

        return ret
