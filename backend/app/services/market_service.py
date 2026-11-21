import pandas as pd
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from backend.app.core.cache import ttl_cache
from backend.app.services import fx_store
from backend.app.services.price_service import get_prices, fetch_yahoo_history

_FETCH_ERRORS = (requests.RequestException, ValueError, KeyError, IndexError, TypeError)

# Last-resort rates, used only when Yahoo FX is unreachable *and* nothing real has ever been
# stored. They are approximations, so every caller gets fx_fallback=True alongside them and must
# surface that to the user.
_FALLBACK_GBPUSD = 1.25
_FALLBACK_GBPEUR = 1.15


def _priced_anything(result: Tuple[Dict[str, Optional[float]], List[Dict[str, str]]]) -> bool:
    """A total outage prices nothing, and caching that leaves the portfolio blank for an hour.

    A *partial* result is still cached, because requiring every ticker would mean one
    permanently delisted holding re-fetched the whole portfolio on every request. The cost of
    that choice is that one ticker's transient failure is still pinned for the TTL; fixing
    that needs a per-ticker cache rather than a per-call one.
    """
    prices, _failures = result
    return any(price is not None for price in prices.values())


@ttl_cache(ttl=3600, cache_if=_priced_anything)
def get_current_prices(tickers: List[str]) -> Tuple[Dict[str, Optional[float]], List[Dict[str, str]]]:
    """Price map plus per-provider failure records. Cached as a pair so a cache hit keeps both."""
    return get_prices(tickers)

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
@ttl_cache(ttl=3600, cache_if=lambda result: not result[1])
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
            print(f"Error fetching FX data for {pair}: {e}.")

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
        print(
            "No stored FX history to fall back on. Using approximate rates "
            f"(GBPUSD={_FALLBACK_GBPUSD}, GBPEUR={_FALLBACK_GBPEUR}); "
            "every non-GBP valuation is now an estimate, not a real quote."
        )
        dates = pd.date_range(start=start_date, end=datetime.now())
        return {
            'GBPUSD=X': pd.Series(_FALLBACK_GBPUSD, index=dates),
            'GBPEUR=X': pd.Series(_FALLBACK_GBPEUR, index=dates),
        }, True

    return {pair: _as_series(rates) for pair, rates in combined.items()}, incomplete

@ttl_cache(ttl=3600, cache_if=lambda result: result is not None)
def _fetch_ohlc(ticker: str, start_date: str) -> Optional[pd.DataFrame]:
    """Returns None on a provider failure, which `cache_if` then refuses to store. That keeps a
    transient 429 from pinning an empty chart for the whole hour, while a successful-but-empty
    answer (delisted ticker) still caches."""
    try:
        return fetch_yahoo_history(ticker, start_date)
    except _FETCH_ERRORS as e:
        print(f"Error fetching OHLC for {ticker}: {e}")
        return None


def get_ohlc(ticker: str, start_date: str) -> pd.DataFrame:
    df = _fetch_ohlc(ticker, start_date)
    return pd.DataFrame(columns=['Date', 'close']) if df is None else df

@ttl_cache(ttl=3600, cache_if=lambda result: result is not None)
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
        print(f"Error fetching price history for {ticker}: {e}")
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

