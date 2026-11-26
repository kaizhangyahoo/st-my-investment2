"""Service-to-service routes, mounted only on data-api (`SERVICE_ROLE=data`).

portfolio-api reaches these through `services/data_client.py`. They carry no user auth: they are
never mounted on the monolith, and the gateway refuses `/api/v1/internal/` outright, so the only
way in is from inside the compose / cluster network. Shapes mirror the in-process functions,
including the degradation signals the public `/market-data` routes drop.
"""
from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.core.tracing import span
from backend.app.services.market_service import (
    fx_covered_through,
    get_current_prices,
    get_historical_fx,
    get_price_history,
)
from backend.app.services.ticker_service import load_ticker_mappings

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)

_MAX_TICKERS = 500


class TickersRequest(BaseModel):
    tickers: List[str] = Field(default_factory=list, max_length=_MAX_TICKERS)


class PriceHistoryRequest(TickersRequest):
    start_date: str


@router.post("/quotes")
def quotes(payload: TickersRequest) -> Dict[str, Any]:
    prices, failures = get_current_prices(payload.tickers)
    return {"prices": prices, "failures": failures}


@router.get("/fx")
def fx(start_date: str) -> Dict[str, Any]:
    series, fallback = get_historical_fx(start_date)
    rates = {
        pair: {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items() if pd.notna(v)}
        for pair, s in series.items()
    }
    return {"rates": rates, "fx_fallback": fallback}


@router.get("/fx/coverage")
def fx_coverage() -> Dict[str, Any]:
    return {"covered_through": fx_covered_through()}


@router.post("/price-history")
def price_history(payload: PriceHistoryRequest) -> Dict[str, Any]:
    """One call per history compute instead of one per ticker."""
    series: Dict[str, Any] = {}
    with span("data.price_history_batch", **{"price.tickers": len(payload.tickers)}):
        for ticker in dict.fromkeys(payload.tickers):
            with span("data.price_history", **{"price.ticker": ticker}):
                df, currency = get_price_history(ticker, payload.start_date)
            points = [
                [pd.Timestamp(d).strftime("%Y-%m-%d"), float(c)]
                for d, c in zip(df["Date"], df["close"])
                if pd.notna(c)
            ]
            series[ticker] = {"currency": currency, "points": points}
    return {"series": series}


@router.get("/ticker-mappings")
def ticker_mappings() -> Dict[str, str]:
    return load_ticker_mappings()
