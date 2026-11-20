from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from backend.app.schemas.portfolio import PortfolioSummary, PortfolioHistoryResponse, CashflowItem
from backend.app.core.security import get_current_user
from backend.app.services import history_service
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

@router.get("/benchmark")
def get_benchmark(symbol: str = "^SPX", user: dict = Depends(get_current_user)):
    return {"symbol": symbol, "data": []}

