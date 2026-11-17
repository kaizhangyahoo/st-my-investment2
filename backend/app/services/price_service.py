"""Market price fetching for the FastAPI backend.

Providers:
- TwelveData: US end-of-day prices (batched, 8 symbols/request on the free tier)
- EODHD: EU/UK real-time/last prices
- Yahoo Finance: fallback for current prices, plus FX and OHLC history

API keys come from backend/.env via `settings`. All HTTP calls have timeouts
and failures are isolated per ticker/provider.
"""
import time
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import pandas as pd
import requests

from backend.app.core.config import settings

TIMEOUT = 15
_TWELVEDATA_BATCH = 8
_EODHD_SUFFIX = {".L": ".LSE", ".DE": ".XETRA"}
_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}
_EMPTY_VALUES = (None, "", "NA", "None")

_session = requests.Session()  # honours HTTP(S)_PROXY / NO_PROXY from env


def _to_float(value) -> Optional[float]:
    if value in _EMPTY_VALUES:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _twelvedata_keys() -> List[str]:
    return [k.strip() for k in (settings.TWELVEDATA_API_KEY or "").split(",") if k.strip()]


def fetch_us_prices(tickers: Iterable[str]) -> Dict[str, Optional[float]]:
    """End-of-day prices for US tickers from TwelveData."""
    keys = _twelvedata_keys()
    prices: Dict[str, Optional[float]] = {}
    if not keys:
        print("TWELVEDATA_API_KEY not set; skipping TwelveData")
        return prices

    symbols = sorted(set(tickers))
    for batch_no, i in enumerate(range(0, len(symbols), _TWELVEDATA_BATCH)):
        if batch_no and batch_no % len(keys) == 0:
            time.sleep(60)  # every key used once -> wait for per-minute quota reset
        batch = symbols[i:i + _TWELVEDATA_BATCH]
        try:
            data = _session.get(
                "https://api.twelvedata.com/eod",
                params={"symbol": ",".join(batch), "apikey": keys[batch_no % len(keys)]},
                timeout=TIMEOUT,
            ).json()
        except (requests.RequestException, ValueError) as e:
            print(f"TwelveData request failed for {batch}: {e}")
            continue
        for t in batch:
            entry = data.get(t) if len(batch) > 1 else data
            prices[t] = _to_float(entry.get("close")) if isinstance(entry, dict) else None
    return prices


def fetch_eodhd_price(ticker: str) -> Optional[float]:
    """Last price from EODHD (real-time endpoint, previousClose fallback)."""
    token = settings.EODHD_API_TOKEN
    if not token:
        return None
    symbol = ticker
    for yahoo_sfx, eod_sfx in _EODHD_SUFFIX.items():
        if ticker.endswith(yahoo_sfx):
            symbol = ticker[: -len(yahoo_sfx)] + eod_sfx
            break
    r = _session.get(
        f"https://eodhd.com/api/real-time/{symbol}",
        params={"api_token": token, "fmt": "json"},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        print(f"EODHD status {r.status_code} for {symbol}")
        return None
    data = r.json()
    if not isinstance(data, dict):
        return None
    return _to_float(data.get("close")) or _to_float(data.get("previousClose"))


def _yahoo_chart(symbol: str, params: dict) -> dict:
    r = _session.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params=params,
        headers=_YAHOO_HEADERS,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["chart"]["result"][0]


def fetch_yahoo_price(ticker: str) -> Optional[float]:
    """Latest price from Yahoo; LSE quotes in pence (GBp) are converted to GBP."""
    meta = _yahoo_chart(ticker, {"range": "5d", "interval": "1d"})["meta"]
    price = _to_float(meta.get("regularMarketPrice"))
    if price is None:
        return None
    return price / 100 if meta.get("currency") == "GBp" else price


def fetch_yahoo_history(symbol: str, start_date: str, interval: str = "1d") -> pd.DataFrame:
    """Daily OHLCV from Yahoo since start_date (YYYY-MM-DD). Indexed and keyed by 'Date'."""
    period1 = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
    result = _yahoo_chart(symbol, {
        "period1": period1,
        "period2": int(time.time()),
        "interval": interval,
        "events": "history",
    })
    df = pd.DataFrame(result["indicators"]["quote"][0])
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Date"] = pd.to_datetime(result["timestamp"], unit="s")
    if interval == "1d":
        df["Date"] = df["Date"].dt.normalize()
    df = df.dropna(subset=["close"])  # Yahoo returns the in-progress bar with null close
    df.index = df["Date"]
    return df


def get_prices(tickers: List[str]) -> Dict[str, Optional[float]]:
    """Current prices: TwelveData for US, EODHD for EU/UK, Yahoo as fallback for all."""
    prices: Dict[str, Optional[float]] = fetch_us_prices(t for t in tickers if "." not in t)

    for t in tickers:
        if prices.get(t) is not None:
            continue
        providers = (fetch_eodhd_price, fetch_yahoo_price) if "." in t else (fetch_yahoo_price,)
        for fetch in providers:
            try:
                price = fetch(t)
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
                print(f"{fetch.__name__} failed for {t}: {e}")
                continue
            if price is not None:
                prices[t] = price
                break
        prices.setdefault(t, None)
    return prices
