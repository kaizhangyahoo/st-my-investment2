"""Market price fetching for the FastAPI backend.

Providers, in the order they are tried:
- Yahoo Finance: primary for every ticker (no key, no quota, ~0.35s/call), plus FX and OHLC history
- TwelveData: tops up US tickers Yahoo could not price (batched, 8 symbols/request on the free tier)
- EODHD: tops up EU/UK tickers Yahoo could not price

Yahoo leads because the paid providers are quota-bound: the EODHD free tier allows 20 requests/day
and then 402s every symbol, and TwelveData's free tier forces a 60s wait between batches.

API keys come from backend/.env via `settings`. All HTTP calls have timeouts
and failures are isolated per ticker/provider.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

from backend.app.core.config import settings

TIMEOUT = 15
_TWELVEDATA_BATCH = 8
_EODHD_SUFFIX = {".L": ".LSE", ".DE": ".XETRA"}
_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}
_EMPTY_VALUES = (None, "", "NA", "None")
_MAX_PARALLEL_FETCHES = 8
_FETCH_ERRORS = (requests.RequestException, ValueError, KeyError, IndexError, TypeError)

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


def _failure(ticker: str, provider: str, reason: str) -> Dict[str, str]:
    return {"ticker": ticker, "provider": provider, "reason": reason}


def fetch_us_prices(tickers: Iterable[str]) -> Tuple[Dict[str, Optional[float]], List[Dict[str, str]]]:
    """End-of-day prices for US tickers from TwelveData."""
    keys = _twelvedata_keys()
    prices: Dict[str, Optional[float]] = {}
    failures: List[Dict[str, str]] = []
    symbols = sorted(set(tickers))
    if not symbols:
        return prices, failures
    if not keys:
        print("TWELVEDATA_API_KEY not set; skipping TwelveData")
        return prices, [_failure(t, "twelvedata", "TWELVEDATA_API_KEY not set") for t in symbols]

    for batch_no, i in enumerate(range(0, len(symbols), _TWELVEDATA_BATCH)):
        batch = symbols[i:i + _TWELVEDATA_BATCH]
        try:
            data = _session.get(
                "https://api.twelvedata.com/eod",
                params={"symbol": ",".join(batch), "apikey": keys[batch_no % len(keys)]},
                timeout=TIMEOUT,
            ).json()
        except (requests.RequestException, ValueError) as e:
            print(f"TwelveData request failed for {batch}: {e}")
            failures.extend(_failure(t, "twelvedata", f"request failed: {e}") for t in batch)
            continue
        for t in batch:
            entry = data.get(t) if len(batch) > 1 else data
            price = _to_float(entry.get("close")) if isinstance(entry, dict) else None
            prices[t] = price
            if price is None:
                detail = entry.get("message") if isinstance(entry, dict) else "no close in response"
                failures.append(_failure(t, "twelvedata", str(detail or "no close in response")))
    return prices, failures


def fetch_eodhd_price(ticker: str) -> Optional[float]:
    """Last price from EODHD (real-time endpoint, previousClose fallback).

    Raises ValueError on a non-200 so the caller can report the reason; the free tier returns 402
    for *every* symbol once the 20-requests/day allowance is spent, not just uncovered exchanges.
    """
    token = settings.EODHD_API_TOKEN
    if not token:
        raise ValueError("EODHD_API_TOKEN not set")
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
    if r.status_code == 402:
        print(f"EODHD daily quota exhausted (free tier, 20/day); {ticker} needs another provider")
        raise ValueError("daily API request limit exceeded (free tier allows 20/day)")
    if r.status_code != 200:
        print(f"EODHD status {r.status_code} for {symbol}")
        raise ValueError(f"HTTP {r.status_code}")
    data = r.json()
    if not isinstance(data, dict):
        return None
    close = _to_float(data.get("close"))
    return close if close is not None else _to_float(data.get("previousClose"))


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
    """Daily OHLCV from Yahoo since start_date (YYYY-MM-DD). Indexed and keyed by 'Date'.

    Closes are left in the quote currency, which `attrs["currency"]` names -- LSE history comes
    back as "GBp" (pence). Callers that sum across currencies must convert; `fetch_yahoo_price`
    normalises pence itself, so the two functions disagree unless you read attrs.
    """
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
    df.attrs["currency"] = result.get("meta", {}).get("currency")
    return df


def _yahoo_price_or_failure(ticker: str) -> Tuple[Optional[float], Optional[Dict[str, str]]]:
    try:
        price = fetch_yahoo_price(ticker)
    except _FETCH_ERRORS as e:
        print(f"fetch_yahoo_price failed for {ticker}: {e}")
        return None, _failure(ticker, "yahoo", str(e))
    if price is None:
        return None, _failure(ticker, "yahoo", "no regularMarketPrice in response")
    return price, None


def get_prices(tickers: List[str]) -> Tuple[Dict[str, Optional[float]], List[Dict[str, str]]]:
    """Current prices: Yahoo for everything, then TwelveData/EODHD for whatever it missed.

    Returns the price map plus one failure record per provider attempt that did not yield a price.
    A ticker can have a failure recorded and still end up priced, which means a fallback worked.
    """
    tickers = list(tickers)
    prices: Dict[str, Optional[float]] = {}
    failures: List[Dict[str, str]] = []
    if not tickers:
        return prices, failures

    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_FETCHES) as pool:
        for ticker, (price, failure) in zip(tickers, pool.map(_yahoo_price_or_failure, tickers)):
            prices[ticker] = price
            if failure:
                failures.append(failure)

    missing = [t for t in tickers if prices.get(t) is None]
    us_prices, us_failures = fetch_us_prices(t for t in missing if "." not in t)
    failures.extend(us_failures)
    for t, price in us_prices.items():
        if price is not None:
            prices[t] = price

    for t in (t for t in missing if "." in t):
        try:
            price = fetch_eodhd_price(t)
        except _FETCH_ERRORS as e:
            failures.append(_failure(t, "eodhd", str(e)))
            continue
        if price is None:
            failures.append(_failure(t, "eodhd", "no close or previousClose in response"))
        else:
            prices[t] = price

    return prices, failures
