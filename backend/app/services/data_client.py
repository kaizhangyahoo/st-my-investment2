"""portfolio-api's view of data-api (P2).

With `DATA_API_URL` unset every call is served in-process by `market_service` /
`ticker_service`, exactly as before the split -- that is the monolith on the laptop and the RPi.
With it set, the same calls go over HTTP to data-api's `/internal` routes, through
`PropagatingSession` so `X-Request-ID` and `traceparent` join both services' logs and traces.

Return shapes match the in-process functions, so callers (and the tests that patch them by name
on `history_service` / `portfolio_engine`) do not know which side answered.

A data-api failure degrades the same way a provider failure does: prices come back unpriced with
a recorded failure, FX comes back flagged as fallback with no coverage, so the callers'
existing withholding rules apply. Ticker mappings are the exception -- an empty map would mark
every row unresolved and be cached for five minutes -- so that failure propagates.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

from backend.app.core.config import settings
from backend.app.core.http import PropagatingSession

logger = logging.getLogger(__name__)

_session: Optional[PropagatingSession] = None

# Same constants `market_service` falls back to; used only when data-api itself is unreachable.
_FALLBACK_FX = {"GBPUSD=X": 1.25, "GBPEUR=X": 1.15}

PriceHistory = Tuple[pd.DataFrame, Optional[str]]


def remote() -> bool:
    return bool((settings.DATA_API_URL or "").strip())


def _http() -> PropagatingSession:
    global _session
    if _session is None:
        _session = PropagatingSession(timeout=settings.DATA_API_TIMEOUT)
    return _session


def _url(path: str) -> str:
    return f"{settings.DATA_API_URL.strip().rstrip('/')}{settings.API_V1_STR}/internal{path}"


def _get(path: str, **params):
    res = _http().get(_url(path), params=params)
    res.raise_for_status()
    return res.json()


def _post(path: str, body: dict):
    res = _http().post(_url(path), json=body)
    res.raise_for_status()
    return res.json()


def _empty_history() -> PriceHistory:
    return pd.DataFrame(columns=["Date", "close"]), None


def get_current_prices(
    tickers: List[str],
) -> Tuple[Dict[str, Optional[float]], List[Dict[str, str]]]:
    if not remote():
        from backend.app.services import market_service
        return market_service.get_current_prices(tickers)
    try:
        body = _post("/quotes", {"tickers": list(tickers)})
        return body["prices"], body["failures"]
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("data-api quotes unavailable: %s", e)
        reason = f"data-api unavailable: {type(e).__name__}"
        return (
            {t: None for t in tickers},
            [{"ticker": t, "provider": "data-api", "reason": reason} for t in tickers],
        )


def get_historical_fx(start_date: str) -> Tuple[Dict[str, pd.Series], bool]:
    if not remote():
        from backend.app.services import market_service
        return market_service.get_historical_fx(start_date)
    try:
        body = _get("/fx", start_date=start_date)
        series = {}
        for pair, rates in body["rates"].items():
            s = pd.Series(rates, dtype="float64")
            s.index = pd.to_datetime(s.index)
            series[pair] = s.sort_index()
        return series, bool(body["fx_fallback"])
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("data-api FX unavailable: %s. Using approximate rates.", e)
        dates = pd.date_range(start=start_date, end=datetime.now())
        return {pair: pd.Series(rate, index=dates) for pair, rate in _FALLBACK_FX.items()}, True


def fx_covered_through() -> Optional[str]:
    if not remote():
        from backend.app.services import market_service
        return market_service.fx_covered_through()
    try:
        return _get("/fx/coverage")["covered_through"]
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("data-api FX coverage unavailable: %s", e)
        return None


def get_price_history(ticker: str, start_date: str) -> PriceHistory:
    if not remote():
        from backend.app.services import market_service
        return market_service.get_price_history(ticker, start_date)
    return get_price_histories([ticker], start_date).get(ticker, _empty_history())


def get_price_histories(tickers: List[str], start_date: str) -> Dict[str, PriceHistory]:
    """Every ticker's closes in one round trip. Only meaningful remotely; in-process callers
    loop `get_price_history` so each ticker keeps its own span."""
    try:
        body = _post("/price-history", {"tickers": list(tickers), "start_date": start_date})
    except (requests.RequestException, ValueError) as e:
        logger.warning("data-api price history unavailable: %s", e)
        return {t: _empty_history() for t in tickers}

    out: Dict[str, PriceHistory] = {}
    for ticker in tickers:
        entry = body.get("series", {}).get(ticker)
        if not entry or not entry.get("points"):
            out[ticker] = _empty_history()
            continue
        df = pd.DataFrame(entry["points"], columns=["Date", "close"])
        df["Date"] = pd.to_datetime(df["Date"])
        out[ticker] = (df, entry.get("currency"))
    return out


def fetch_ticker_mappings() -> Dict[str, str]:
    """Raises on failure: see the module docstring."""
    return _get("/ticker-mappings")
