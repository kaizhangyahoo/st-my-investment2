from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Any, Optional
from backend.app.schemas.portfolio import PortfolioSummary, PortfolioHistoryPoint, CashflowItem
from backend.app.core.security import get_current_user
import json
import os
from backend.app.core.config import settings

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

@router.get("/history", response_model=List[PortfolioHistoryPoint])
def get_history(account_id: str = "default", user: dict = Depends(get_current_user)):
    filepath = settings.PORTFOLIO_VALUES_FILE
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                account_data = data.get(account_id, {})
                points = [{"date": k, "value": float(v)} for k, v in account_data.items() if v is not None]
                points.sort(key=lambda x: x["date"])
                return points
        except Exception:
            pass
    return []

@router.get("/benchmark")
def get_benchmark(symbol: str = "^SPX", user: dict = Depends(get_current_user)):
    return {"symbol": symbol, "data": []}

