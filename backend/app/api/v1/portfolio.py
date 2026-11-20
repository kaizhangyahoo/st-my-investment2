from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import pandas as pd
from backend.app.schemas.portfolio import (
    BenchmarkResponse,
    CashflowItem,
    PortfolioHistoryResponse,
    PortfolioMetricsResponse,
    PortfolioSummary,
)
from backend.app.core.security import get_current_user
from backend.app.services import history_service, risk_metrics
from backend.app.services.market_service import get_price_history
from backend.app.api.v1.trades import get_or_load_trade_df

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

@router.get("/history", response_model=PortfolioHistoryResponse)
def get_history(
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Historical GBP portfolio value, read from `user_portfolio_values.json` (KAN-39).

    Read-only: generating values is `POST /history/compute` (KAN-19), so a provider gap
    there (e.g. delisted tickers) cannot blank the chart.

    Always one account's stored series, verbatim. `account_id` defaults to the richest stored
    account, because the file is keyed per account and the accounts in it are not all the same
    person's — summing them produced a number nobody holds (KAN-46).

    `fillable_gap` says whether recomputing could actually add anything: only the caller's own
    key is computable here, and only a series that stops short of today has a tail to extend.
    """
    own_key = history_service.portfolio_key(user.get("sub", "default"))
    key = account_id or history_service.default_account() or own_key
    points = history_service.read_cached_series(key)
    return {
        "points": points,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "data_quality": {"degraded": False},
        "accounts": history_service.stored_accounts(),
        "account_id": key,
        "fillable_gap": key == own_key and history_service.is_behind(points),
    }

@router.post("/history/compute", response_model=PortfolioHistoryResponse)
def compute_history(refresh: bool = False, user: dict = Depends(get_current_user)):
    """Value the caller's uploaded trade history per day and persist it to the JSON (KAN-19).

    `data_quality` reports on this run only; the stored series is what the chart reads.
    """
    key = history_service.portfolio_key(user.get("sub", "default"))
    df, _ = get_or_load_trade_df(user.get("sub", "default"))
    if df is None:
        result = {
            "points": [],
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "data_quality": {"degraded": False},
        }
    else:
        result = history_service.compute_history(df, key, force_recompute=refresh)
    return {**result, "accounts": history_service.stored_accounts(), "account_id": key}

@router.get("/metrics", response_model=PortfolioMetricsResponse)
def get_metrics(
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Risk and return statistics for one stored series, per timeframe (KAN-27).

    Separate from `/history` so the account's series is fetched once and the tiles can switch
    windows without another request. The account is resolved exactly as `/history` resolves it,
    so both describe the same series.
    """
    key = account_id or history_service.default_account() or history_service.portfolio_key(
        user.get("sub", "default")
    )
    points = history_service.read_cached_series(key)
    return {"account_id": key, "windows": risk_metrics.all_windows(points)}

@router.get("/benchmark", response_model=BenchmarkResponse)
def get_benchmark(
    symbol: str = "VUSA.L",
    start_date: str = "2018-01-01",
    user: dict = Depends(get_current_user),
):
    """Daily closes for a comparison index, for rebasing against the equity curve (KAN-27).

    Defaults to the LSE-listed S&P 500 tracker rather than `^GSPC` so the comparison is in the
    same currency the portfolio is valued in, and an unreachable provider yields an empty series
    with a reason rather than a flat line the user would read as real.
    """
    df, currency = get_price_history(symbol, start_date)
    if df.empty:
        return {
            "symbol": symbol,
            "currency": currency,
            "points": [],
            "unavailable_reason": f"No closes returned for {symbol} since {start_date}",
        }
    points = [
        {"date": pd.Timestamp(row.Date).strftime("%Y-%m-%d"), "value": float(row.close)}
        for row in df.itertuples()
        if pd.notnull(row.close)
    ]
    return {"symbol": symbol, "currency": currency, "points": points}

