from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Optional, Any
from backend.app.services.market_service import get_current_prices, get_historical_fx, get_ohlc
from backend.app.core.security import get_current_user

router = APIRouter(prefix="/market-data", tags=["market-data"])

@router.get("/quotes")
def get_quotes(tickers: str = Query(..., description="Comma separated tickers"), user: dict = Depends(get_current_user)):
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    return get_current_prices(ticker_list)

@router.get("/fx")
def get_fx(start_date: str = "2023-01-01", user: dict = Depends(get_current_user)):
    fx = get_historical_fx(start_date)
    return {pair: series.to_dict() for pair, series in fx.items()}

@router.get("/ohlc/{ticker}")
def get_ticker_ohlc(ticker: str, start_date: str = "2023-01-01", user: dict = Depends(get_current_user)):
    df = get_ohlc(ticker, start_date)
    return df.to_dict(orient="records")

