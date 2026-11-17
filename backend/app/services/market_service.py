import pandas as pd
import requests
from typing import Dict, List, Optional
from datetime import datetime
from backend.app.core.cache import ttl_cache
from backend.app.services.price_service import get_prices, fetch_yahoo_history

_FETCH_ERRORS = (requests.RequestException, ValueError, KeyError, IndexError, TypeError)


@ttl_cache(ttl=3600)
def get_current_prices(tickers: List[str]) -> Dict[str, Optional[float]]:
    return get_prices(tickers)

@ttl_cache(ttl=3600)
def get_historical_fx(start_date: str) -> Dict[str, pd.Series]:
    fx_data = {}
    try:
        for pair in ['GBPUSD=X', 'GBPEUR=X']:
            fx_data[pair] = fetch_yahoo_history(pair, start_date)['close']
    except _FETCH_ERRORS as e:
        print(f"Error fetching FX data: {e}")
        dates = pd.date_range(start=start_date, end=datetime.now())
        fx_data['GBPUSD=X'] = pd.Series(1.25, index=dates)
        fx_data['GBPEUR=X'] = pd.Series(1.15, index=dates)
    return fx_data

def get_ohlc(ticker: str, start_date: str) -> pd.DataFrame:
    try:
        return fetch_yahoo_history(ticker, start_date)
    except _FETCH_ERRORS as e:
        print(f"Error fetching OHLC for {ticker}: {e}")
        return pd.DataFrame(columns=['Date', 'close'])

