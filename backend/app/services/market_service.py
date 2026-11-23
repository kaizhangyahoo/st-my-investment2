import logging
import pandas as pd
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from backend.app.core.cache import MISS, cache, ttl_cache
from backend.app.core.tracing import annotate, span
from backend.app.services import fx_store
from backend.app.services.price_service import get_prices, fetch_yahoo_history

logger = logging.getLogger(__name__)

_FETCH_ERRORS = (requests.RequestException, ValueError, KeyError, IndexError, TypeError)

# Last-resort rates, used only when Yahoo FX is unreachable *and* nothing real has ever been
# stored. They are approximations, so every caller gets fx_fallback=True alongside them and must
# surface that to the user.
_FALLBACK_GBPUSD = 1.25
_FALLBACK_GBPEUR = 1.15


_PRICE_TTL = 3600


def _price_key(ticker: str) -> Tuple[str, str]:
    """Namespaced so it cannot collide with `ttl_cache`'s own 3-tuple keys in the same store."""
    return ("current_price", ticker)


def get_current_prices(
    tickers: List[str],
) -> Tuple[Dict[str, Optional[float]], List[Dict[str, str]]]:
    """Current prices for `tickers`, plus the failures recorded while fetching them.

    Cached one ticker at a time rather than per call. A key built from the whole requested list
    stored one ticker's transient failure beside thirty good prices and served the lot for the
    rest of the hour, with nothing in `backend/` able to clear it; it also meant any change to
    the position set -- one new trade, one position closed -- discarded every price at once, and
    let an arbitrary ticker list grow the key space one entry per permutation (KAN-54).

    Only successful prices are stored, so an unpriced ticker leaves its key free and the next
    request retries just that one. Failures therefore always describe this request's own
    attempts: a cache hit contributes none, which is what stops `data_quality.failures` from
    reporting a provider error that happened an hour ago.
    """
    requested = list(dict.fromkeys(tickers))
    cached: Dict[str, float] = {}
    uncached: List[str] = []
    for ticker in requested:
        price = cache.get(_price_key(ticker), MISS)
        if price is MISS:
            uncached.append(ticker)
        else:
            cached[ticker] = price

    # On the request span, not a span of their own: a hit is the absence of work, and one span
    # per lookup would dwarf the trace. `cache.current_price.hit` means every ticker came from
    # the cache, so a response that touched no provider is distinguishable from one that did.
    #
    # Counted by hand rather than through `record_cache_hit`: this is one pass over the whole
    # requested list, so a single accurate flush is available here, and there is no span of this
    # function's own for an accumulator to land on.
    annotate(**{
        "cache.current_price.hit": not uncached,
        "cache.current_price.hits": len(cached),
        "cache.current_price.misses": len(uncached),
    })

    if not uncached:
        return dict(cached), []

    # One call for the whole uncached subset, so `get_prices` keeps its thread pool and
    # TwelveData still batches 8 symbols per request instead of one request per ticker.
    fetched, failures = get_prices(uncached)
    for ticker, price in fetched.items():
        if price is not None:
            cache.set(_price_key(ticker), price, ttl=_PRICE_TTL)

    return {t: fetched.get(t, cached.get(t)) for t in requested}, failures

def _rate_map(rows: pd.DataFrame) -> Dict[str, float]:
    """A Yahoo history frame as `{"YYYY-MM-DD": rate}`, which is what the store speaks."""
    closes = rows["close"]
    days = pd.DatetimeIndex(pd.to_datetime(rows["Date"])).normalize().strftime("%Y-%m-%d")
    return {day: float(v) for day, v in zip(days, closes) if pd.notna(v)}


def _as_series(rates: Dict[str, float]) -> pd.Series:
    """Ascending date-indexed series. The order matters: callers wanting the current rate read
    `.iloc[-1]`, and a merge of stored and freshly fetched closes is not sorted by construction."""
    series = pd.Series(rates, dtype="float64")
    series.index = pd.to_datetime(series.index)
    return series.sort_index()


# Only a complete, real answer is cached. A fetch that failed must leave the key free, or one
# SSL error outlives the outage by an hour (KAN-53) -- here it would also hold back today's rate
# while `fx_store` is perfectly able to serve yesterday's.
@ttl_cache(ttl=3600, cache_if=lambda result: not result[1], name="historical_fx")
def get_historical_fx(start_date: str) -> Tuple[Dict[str, pd.Series], bool]:
    """Historical GBP crosses, plus a flag saying whether the FX feed answered in full.

    Real closes are persisted (`fx_store`) and reused, so an unreachable provider degrades to the
    last real rate rather than to a guess, and the usual request fetches a week instead of years.
    The approximated constants are now reached only with an empty store -- a first run that cannot
    reach the provider at all. Dates the store does not cover are *not* filled in here: the caller
    decides what to do about them, and `history_service` withholds them rather than persisting a
    valuation built on a rate nobody quoted (KAN-55).
    """
    stored = fx_store.read_rates()
    fetch_start = fx_store.fetch_from(start_date, stored)
    fetched: Dict[str, Dict[str, float]] = {}
    incomplete = False

    for pair in fx_store.PAIRS:
        try:
            rates = _rate_map(fetch_yahoo_history(pair, fetch_start))
            if not rates:
                raise ValueError(f"no usable closes since {fetch_start}")
            fetched[pair] = rates
        except _FETCH_ERRORS as e:
            incomplete = True
            logger.warning(
                "Error fetching FX data for %s: %s. Stored history will be used instead.", pair, e
            )

    if fetched:
        fx_store.merge_rates(fetched)

    # Trimmed to the window asked for: the store can reach further back than this caller does,
    # and handing back rates it did not ask for would change what `/market-data/fx` returns.
    combined = {
        pair: {
            day: rate
            for day, rate in {**stored.get(pair, {}), **fetched.get(pair, {})}.items()
            if day >= start_date
        }
        for pair in fx_store.PAIRS
    }
    if any(not rates for rates in combined.values()):
        logger.error(
            "No stored FX history to fall back on. Using approximate rates "
            "(GBPUSD=%s, GBPEUR=%s); every non-GBP valuation is now an estimate, "
            "not a real quote.",
            _FALLBACK_GBPUSD,
            _FALLBACK_GBPEUR,
        )
        dates = pd.date_range(start=start_date, end=datetime.now())
        return {
            'GBPUSD=X': pd.Series(_FALLBACK_GBPUSD, index=dates),
            'GBPEUR=X': pd.Series(_FALLBACK_GBPEUR, index=dates),
        }, True

    return {pair: _as_series(rates) for pair, rates in combined.items()}, incomplete

@ttl_cache(ttl=3600, cache_if=lambda result: result is not None, name="ohlc")
def _fetch_ohlc(ticker: str, start_date: str) -> Optional[pd.DataFrame]:
    """Returns None on a provider failure, which `cache_if` then refuses to store. That keeps a
    transient 429 from pinning an empty chart for the whole hour, while a successful-but-empty
    answer (delisted ticker) still caches."""
    try:
        return fetch_yahoo_history(ticker, start_date)
    except _FETCH_ERRORS as e:
        logger.debug("Error fetching OHLC for %s: %s", ticker, e)
        return None


def get_ohlc(ticker: str, start_date: str) -> pd.DataFrame:
    # The span exists to give `cache.ohlc.*` somewhere to land: a counter with no enclosing span
    # is dropped silently, and the chart route opens none of its own.
    with span("market.ohlc"):
        df = _fetch_ohlc(ticker, start_date)
        return pd.DataFrame(columns=['Date', 'close']) if df is None else df

@ttl_cache(ttl=3600, cache_if=lambda result: result is not None, name="price_history")
def _fetch_price_history(
    ticker: str, start_date: str
) -> Optional[Tuple[pd.DataFrame, Optional[str]]]:
    """None on a provider failure, so `cache_if` leaves the key free for the next request.

    The failure has to be signalled by control flow rather than by inspecting the returned
    pair, because a genuine success can carry a null currency: `attrs["currency"]` is whatever
    Yahoo put in `meta`, and an empty frame is the right answer for a delisted ticker.
    """
    try:
        df = fetch_yahoo_history(ticker, start_date)
    except _FETCH_ERRORS as e:
        logger.debug("Error fetching price history for %s: %s", ticker, e)
        return None
    return df[['Date', 'close']], df.attrs.get("currency")


def get_price_history(ticker: str, start_date: str) -> Tuple[pd.DataFrame, Optional[str]]:
    """Daily closes for one ticker plus the currency they are quoted in.

    The currency is returned alongside rather than folded into the frame because the caller has
    to convert across several crosses and "GBp" needs a different rule from a real FX pair.
    An unreachable ticker yields an empty frame and `None`, which the caller must treat as
    missing data -- not as a zero-valued holding.
    """
    fetched = _fetch_price_history(ticker, start_date)
    return (pd.DataFrame(columns=['Date', 'close']), None) if fetched is None else fetched

