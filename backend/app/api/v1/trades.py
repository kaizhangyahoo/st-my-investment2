from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from typing import List, Dict, Any
import pandas as pd
import io
from backend.app.services.portfolio_engine import calculate_positions_from_df, calculate_cashflow_waterfall
from backend.app.schemas.portfolio import PortfolioSummary, CashflowItem
from backend.app.core.security import get_current_user

router = APIRouter(prefix="/trades", tags=["trades"])

# In-memory store for uploaded trade data per session/demo
_LAST_TRADE_DF: Dict[str, pd.DataFrame] = {}
_LAST_TRANSACTION_DF: Dict[str, pd.DataFrame] = {}

@router.post("/upload")
async def upload_files(files: List[UploadFile] = File(...), user: dict = Depends(get_current_user)):
    user_id = user.get("sub", "default")
    results = {"trade_files": [], "transaction_files": [], "errors": []}

    for f in files:
        contents = await f.read()
        try:
            df = pd.read_csv(io.BytesIO(contents))
            if f.filename.startswith("Trade") or "Market" in df.columns:
                _LAST_TRADE_DF[user_id] = df
                results["trade_files"].append(f.filename)
            elif f.filename.startswith("Transaction") or "PL Amount" in df.columns:
                _LAST_TRANSACTION_DF[user_id] = df
                results["transaction_files"].append(f.filename)
        except Exception as e:
            results["errors"].append(f"Failed to parse {f.filename}: {str(e)}")

    return results

@router.get("/summary", response_model=PortfolioSummary)
def get_portfolio_summary(user: dict = Depends(get_current_user)):
    user_id = user.get("sub", "default")
    df = _LAST_TRADE_DF.get(user_id)
    if df is None:
        # Return empty summary structure
        return {
            "total_market_value_gbp": 0.0,
            "total_invested_cash": 0.0,
            "total_pnl_gbp": 0.0,
            "currency_allocation": {"usd_gbp": 0.0, "eur_gbp": 0.0, "gbp": 0.0, "total_gbp": 0.0},
            "positions": []
        }
    return calculate_positions_from_df(df)

@router.get("/waterfall", response_model=List[CashflowItem])
def get_cashflow_waterfall(user: dict = Depends(get_current_user)):
    user_id = user.get("sub", "default")
    df = _LAST_TRANSACTION_DF.get(user_id)
    if df is None:
        return []
    return calculate_cashflow_waterfall(df)

