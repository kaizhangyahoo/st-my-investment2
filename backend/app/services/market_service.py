import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from backend.app.core.cache import ttl_cache

@ttl_cache(ttl=3600)
def get_current_prices(tickers: List[str]) -> Dict[str, Optional[float]]:
    prices: Dict[str, Optional[float]] = {}
    eu_tickers = [t for t in tickers if t.endswith('.L') or t.endswith('.DE')]
    us_tickers = [t for t in tickers if '.' not in t]

    try:
        from getEODprice import getEODpriceUSA, getEODpriceFromEODHD
        if us_tickers:
            prices.update(getEODpriceUSA(us_tickers))
        if eu_tickers:
            prices.update(getEODpriceFromEODHD(eu_tickers))
    except Exception as e:
        print(f"Error getting prices: {e}")

    for t in tickers:
        if t not in prices:
            prices[t] = None
    return prices

@ttl_cache(ttl=3600)
def get_historical_fx(start_date: str) -> Dict[str, pd.Series]:
    fx_data = {}
    try:
        from market_data_api import OHLC_YahooFinance
        for pair in ['GBPUSD=X', 'GBPEUR=X']:
            data = OHLC_YahooFinance(pair, start_date).yahooDataV8()
            data.index = pd.to_datetime(data.index)
            fx_data[pair] = data['close']
    except Exception as e:
        print(f"Error fetching FX data: {e}")
        dates = pd.date_range(start=start_date, end=datetime.now())
        fx_data['GBPUSD=X'] = pd.Series(1.25, index=dates)
        fx_data['GBPEUR=X'] = pd.Series(1.15, index=dates)
    return fx_data

def get_ohlc(ticker: str, start_date: str) -> pd.DataFrame:
    try:
        from market_data_api import OHLC_YahooFinance
        data = OHLC_YahooFinance(ticker, start_date).yahooDataV8()
        data['Date'] = pd.to_datetime(data['Date'])
        return data
    except Exception as e:
        print(f"Error fetching OHLC for {ticker}: {e}")
        return pd.DataFrame(columns=['Date', 'close'])

