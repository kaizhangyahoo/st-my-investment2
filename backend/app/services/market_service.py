import pandas as pd
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from backend.app.core.cache import ttl_cache
from backend.app.services.price_service import get_prices, fetch_yahoo_history

_FETCH_ERRORS = (requests.RequestException, ValueError, KeyError, IndexError, TypeError)

# Last-resort rates used only when Yahoo FX is unreachable. They are approximations, so every
# caller gets fx_fallback=True alongside them and must surface that to the user.
_FALLBACK_GBPUSD = 1.25
_FALLBACK_GBPEUR = 1.15


@ttl_cache(ttl=3600)
def get_current_prices(tickers: List[str]) -> Tuple[Dict[str, Optional[float]], List[Dict[str, str]]]:
    """Price map plus per-provider failure records. Cached as a pair so a cache hit keeps both."""
    return get_prices(tickers)

@ttl_cache(ttl=3600)
def get_historical_fx(start_date: str) -> Tuple[Dict[str, pd.Series], bool]:
    """Historical GBP crosses, plus a flag saying whether the rates are real or approximated."""
    fx_data = {}
    try:
        for pair in ['GBPUSD=X', 'GBPEUR=X']:
            series = fetch_yahoo_history(pair, start_date)['close']
            if series.empty:
                raise ValueError(f"{pair} returned no usable closes")
            fx_data[pair] = series
    except _FETCH_ERRORS as e:
        print(
            f"Error fetching FX data: {e}. Falling back to approximate rates "
            f"(GBPUSD={_FALLBACK_GBPUSD}, GBPEUR={_FALLBACK_GBPEUR}); "
            "every non-GBP valuation is now an estimate, not a real quote."
        )
        dates = pd.date_range(start=start_date, end=datetime.now())
        fx_data['GBPUSD=X'] = pd.Series(_FALLBACK_GBPUSD, index=dates)
        fx_data['GBPEUR=X'] = pd.Series(_FALLBACK_GBPEUR, index=dates)
        return fx_data, True
    return fx_data, False

@ttl_cache(ttl=3600)
def _fetch_ohlc(ticker: str, start_date: str) -> Optional[pd.DataFrame]:
    """Returns None on a provider failure, which `ttl_cache` reads as a miss and so does not
    serve. That keeps a transient 429 from pinning an empty chart for the whole hour, while a
    successful-but-empty answer (delisted ticker) still caches."""
    try:
        return fetch_yahoo_history(ticker, start_date)
    except _FETCH_ERRORS as e:
        print(f"Error fetching OHLC for {ticker}: {e}")
        return None


def get_ohlc(ticker: str, start_date: str) -> pd.DataFrame:
    df = _fetch_ohlc(ticker, start_date)
    return pd.DataFrame(columns=['Date', 'close']) if df is None else df

@ttl_cache(ttl=3600)
def get_price_history(ticker: str, start_date: str) -> Tuple[pd.DataFrame, Optional[str]]:
    """Daily closes for one ticker plus the currency they are quoted in.

    The currency is returned alongside rather than folded into the frame because the caller has
    to convert across several crosses and "GBp" needs a different rule from a real FX pair.
    An unreachable ticker yields an empty frame and `None`, which the caller must treat as
    missing data -- not as a zero-valued holding.
    """
    try:
        df = fetch_yahoo_history(ticker, start_date)
    except _FETCH_ERRORS as e:
        print(f"Error fetching price history for {ticker}: {e}")
        return pd.DataFrame(columns=['Date', 'close']), None
    return df[['Date', 'close']], df.attrs.get("currency")

