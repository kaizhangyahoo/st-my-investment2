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
    refresh: bool = False,
    user: dict = Depends(get_current_user),
):
    """Historical GBP value of the caller's portfolio.

    `account_id` reads a stored series verbatim instead of computing one, which is how the
    Trading 212 keys the legacy Streamlit app writes ("QX2B3") stay reachable.
    """
    if account_id:
        return {
            "points": history_service.read_cached_series(account_id),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "data_quality": {"degraded": False},
        }

    user_id = user.get("sub", "default")
    key = history_service.portfolio_key(user_id)
    df, _ = get_or_load_trade_df(user_id)
    if df is None:
        return {
            "points": [],
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "data_quality": {"degraded": False},
        }
    return history_service.compute_history(df, key, force_recompute=refresh)

@router.get("/benchmark")
def get_benchmark(symbol: str = "^SPX", user: dict = Depends(get_current_user)):
    return {"symbol": symbol, "data": []}

