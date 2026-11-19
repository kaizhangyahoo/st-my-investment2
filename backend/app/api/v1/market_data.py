from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Optional, Any
from backend.app.services.market_service import get_current_prices, get_historical_fx, get_ohlc
from backend.app.core.security import get_current_user

router = APIRouter(prefix="/market-data", tags=["market-data"])

@router.get("/quotes")
def get_quotes(tickers: str = Query(..., description="Comma separated tickers"), user: dict = Depends(get_current_user)):
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    prices, _failures = get_current_prices(ticker_list)
    return prices

@router.get("/fx")
def get_fx(start_date: str = "2023-01-01", user: dict = Depends(get_current_user)):
    fx, _fx_fallback = get_historical_fx(start_date)
    return {pair: series.to_dict() for pair, series in fx.items()}

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

