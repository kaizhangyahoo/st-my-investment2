import logging

from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Optional, Any
from backend.app.services.market_service import (
    fx_covered_through,
    get_current_prices,
    get_historical_fx,
    get_ohlc,
)
from backend.app.core.diagnostics import log_data_quality
from backend.app.core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market-data", tags=["market-data"])

@router.get("/quotes")
def get_quotes(tickers: str = Query(..., description="Comma separated tickers"), user: dict = Depends(get_current_user)):
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    prices, failures = get_current_prices(ticker_list)
    # Both routes here bound a degradation signal and dropped it, so a null price was
    # indistinguishable in the logs from a ticker nobody asked about. No service hands back a
    # `data_quality` block on this path, so the block is assembled from what the call returned.
    # Read-only: the response keeps its shape, and serving the FX fallback is KAN-62's.
    unpriced = [t for t, price in prices.items() if price is None]
    log_data_quality(logger, "market_data.quotes", {
        "degraded": bool(unpriced),
        "unpriced_tickers": unpriced,
        "failures": failures,
    })
    return prices

@router.get("/fx")
def get_fx(start_date: str = "2023-01-01", user: dict = Depends(get_current_user)):
    fx, fx_fallback = get_historical_fx(start_date)
    log_data_quality(logger, "market_data.fx", {
        "degraded": fx_fallback,
        "fx_fallback": fx_fallback,
    })
    # With no real close stored inside the window, the series are the approximated constants
    # broadcast across every date. Withhold them rather than serve a flat line the client would
    # read as real (KAN-62); pair keys stay so the shape does not change, and it stays a 200.
    covered = fx_covered_through()
    approximated = fx_fallback and (covered is None or covered < start_date)
    body: Dict[str, Any] = {
        pair: {} if approximated else series.to_dict() for pair, series in fx.items()
    }
    data_quality: Dict[str, Any] = {"degraded": fx_fallback, "fx_fallback": fx_fallback}
    if approximated:
        data_quality["unavailable_reason"] = (
            "FX provider unreachable and no real rates stored; approximated rates withheld"
        )
    body["data_quality"] = data_quality
    return body

@router.get("/ohlc/{ticker}")
def get_ticker_ohlc(ticker: str, start_date: str = "2023-01-01", user: dict = Depends(get_current_user)):
    df = get_ohlc(ticker, start_date)
    if df.empty:
        return {"ticker": ticker, "currency": None, "points": []}
    # Only Date/close: open/high/volume can carry NaN, which is not valid JSON.
    points = [
        {"date": d.strftime("%Y-%m-%d"), "close": float(c)}
        for d, c in zip(df["Date"], df["close"])
    ]
    return {"ticker": ticker, "currency": df.attrs.get("currency"), "points": points}

