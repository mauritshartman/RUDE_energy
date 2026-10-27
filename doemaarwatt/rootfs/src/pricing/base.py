'''What every price source has in common.

A source does one thing: hand back the day-ahead prices it can currently supply, as a mapping of timezone
aware timestamps (in the configured timezone, spaced at the configured resolution) to a price in EUR/kWh.
Everything around that - caching, retrying, predicting the night prices, answering what the price is right
now - belongs to the PriceManager in price.py and is the same whichever source is configured.
'''
from abc import ABC, abstractmethod
from datetime import datetime as dt


class PriceSourceAuthError(Exception):
    '''The credential a price source needs is missing, wrong, or not activated yet.

    Kept apart from every other failure because no number of retries can resolve it: the fetch loop in
    price.py gives up at once instead of spending requests (and, for a source with a monthly budget like
    Enever, a month of them - see issue #43) on a call that cannot succeed.
    '''


class BasePriceSource(ABC):

    @abstractmethod
    async def fetch(self) -> dict[dt, float]:
        '''Return the day-ahead prices this source can supply right now: today, and tomorrow once it has been
        published. A source leaves out what it does not have rather than failing, so a caller checks what came
        back rather than assuming two full days.

        Raises PriceSourceAuthError when the credential is the problem, and any other exception when the
        failure is one that retrying might get past.
        '''
        raise NotImplementedError
