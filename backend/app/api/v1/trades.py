from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
import io
import os
import glob
import re
from datetime import datetime

from backend.app.services.portfolio_engine import calculate_positions_from_df, calculate_cashflow_waterfall, empty_data_quality
from backend.app.services.ticker_service import find_unresolved_symbols, load_ticker_mappings, resolve_ticker
from backend.app.schemas.portfolio import PortfolioSummary, CashflowItem, TradeActivityItem
from backend.app.core.security import get_current_user

router = APIRouter(prefix="/trades", tags=["trades"])

# In-memory store for uploaded trade data per session/demo
_LAST_TRADE_DF: Dict[str, pd.DataFrame] = {}
_LAST_TRANSACTION_DF: Dict[str, pd.DataFrame] = {}
_LAST_TRADE_FILENAME: Dict[str, str] = {}
_LAST_TRANSACTION_FILENAME: Dict[str, str] = {}
_USER_MANUAL_UPLOAD: Dict[str, bool] = {}

def parse_file_date(filepath: str) -> datetime:
    """Extract date from filename (e.g. DD-MM-YYYY) or fallback to file modification time."""
    filename = os.path.basename(filepath)
    matches = re.findall(r'\((\d{2}-\d{2}-\d{4})\)', filename)
    if matches:
        try:
            return datetime.strptime(matches[-1], '%d-%m-%Y')
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(os.path.getmtime(filepath))
    except Exception:
        return datetime.min

def find_latest_download_files() -> Tuple[Optional[str], Optional[str]]:
    """
    Search ~/Downloads for Tr*.csv files and select the ones with the latest date.
    Returns (latest_trade_file, latest_transaction_file).
    """
    downloads_dir = os.path.expanduser('~/Downloads')
    if not os.path.isdir(downloads_dir):
        return None, None

    patterns = ['Trade*.csv', 'Transaction*.csv', 'Tr*.csv']
    found_files = set()
    for pattern in patterns:
        found_files.update(glob.glob(os.path.join(downloads_dir, pattern)))

    trade_candidates: List[Tuple[datetime, str]] = []
    trans_candidates: List[Tuple[datetime, str]] = []
    generic_candidates: List[Tuple[datetime, str]] = []

    for f in found_files:
        basename = os.path.basename(f)
        dt = parse_file_date(f)
        if basename.startswith('Trade'):
            trade_candidates.append((dt, f))
        elif basename.startswith('Transaction'):
            trans_candidates.append((dt, f))
        else:
            generic_candidates.append((dt, f))

    trade_candidates.sort(key=lambda x: x[0], reverse=True)
    trans_candidates.sort(key=lambda x: x[0], reverse=True)
    generic_candidates.sort(key=lambda x: x[0], reverse=True)

    latest_trade = trade_candidates[0][1] if trade_candidates else None
    latest_trans = trans_candidates[0][1] if trans_candidates else None

    # Fallback to generic Tr*.csv if specific prefixes weren't found
    if not latest_trade and generic_candidates:
        latest_trade = generic_candidates[0][1]
    if not latest_trans and len(generic_candidates) > 1:
        latest_trans = generic_candidates[1][1]

    return latest_trade, latest_trans

def extract_trade_activities(df: pd.DataFrame, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Extract formatted trade activity records (newest first) from TradeHistory DataFrame.

    Dates are emitted as ISO `YYYY-MM-DD` so the client can filter by quarter/year.
    """
    try:
        df_copy = df.copy()
        if 'TextDate' in df_copy.columns:
            df_copy['ParsedDate'] = pd.to_datetime(df_copy['TextDate'], errors='coerce', dayfirst=True)
            df_copy = df_copy.sort_values(by='ParsedDate', ascending=False)
        if limit is not None:
            df_copy = df_copy.head(limit)

        ticker_map = load_ticker_mappings()
        activities: List[Dict[str, Any]] = []
        for _, row in df_copy.iterrows():
            direction = str(row.get('Direction', '')).upper()
            qty = float(row.get('Quantity', 0)) if pd.notnull(row.get('Quantity')) else 0.0
            act = 'BUY' if direction == 'BUY' or qty > 0 else 'SELL'
            price = row.get('Price', 0.0)
            cost = row.get('Cost/Proceeds', 0.0)
            parsed = row.get('ParsedDate')
            market = str(row.get('Market', ''))
            activities.append({
                'qty': abs(qty),
                'fill': f"{price}",
                'value': f"£{abs(cost):,.2f}" if pd.notnull(cost) else "",
                'date': parsed.strftime('%Y-%m-%d') if pd.notnull(parsed) else str(row.get('TextDate', '')),
                'time': str(row.get('Time', '')),
                'activity': act,
                'market': market,
                'ticker': resolve_ticker(market, ticker_map),
            })
        return activities
    except Exception:
        return []

def get_or_load_trade_df(user_id: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Get active trade df from memory or autoload the latest Tr*.csv from ~/Downloads."""
    df = _LAST_TRADE_DF.get(user_id)
    filename = _LAST_TRADE_FILENAME.get(user_id)
    if df is not None:
        return df, filename

    # If the user performed a manual upload that lacked trade history,
    # do NOT auto-load from ~/Downloads behind the scenes.
    if _USER_MANUAL_UPLOAD.get(user_id) and user_id in _LAST_TRANSACTION_DF:
        return None, None

    # Search ~/Downloads
    latest_trade, latest_trans = find_latest_download_files()
    if latest_trade and os.path.exists(latest_trade):
        try:
            loaded_df = pd.read_csv(latest_trade)
            _LAST_TRADE_DF[user_id] = loaded_df
            _LAST_TRADE_FILENAME[user_id] = os.path.basename(latest_trade)
            if latest_trans and os.path.exists(latest_trans) and user_id not in _LAST_TRANSACTION_DF:
                try:
                    _LAST_TRANSACTION_DF[user_id] = pd.read_csv(latest_trans)
                    _LAST_TRANSACTION_FILENAME[user_id] = os.path.basename(latest_trans)
                except Exception:
                    pass
            return loaded_df, os.path.basename(latest_trade)
        except Exception:
            pass
    return None, None

@router.post("/upload")
async def upload_files(files: List[UploadFile] = File(...), user: dict = Depends(get_current_user)):
    user_id = user.get("sub", "default")
    results = {"trade_files": [], "transaction_files": [], "errors": []}
    _USER_MANUAL_UPLOAD[user_id] = True

    uploaded_trade = False
    uploaded_transaction = False

    for f in files:
        contents = await f.read()
        try:
            df = pd.read_csv(io.BytesIO(contents))
            if f.filename.startswith("Trade") or "Market" in df.columns:
                _LAST_TRADE_DF[user_id] = df
                _LAST_TRADE_FILENAME[user_id] = f.filename
                results["trade_files"].append(f.filename)
                uploaded_trade = True
            elif f.filename.startswith("Transaction") or "PL Amount" in df.columns:
                _LAST_TRANSACTION_DF[user_id] = df
                _LAST_TRANSACTION_FILENAME[user_id] = f.filename
                results["transaction_files"].append(f.filename)
                uploaded_transaction = True
        except Exception as e:
            results["errors"].append(f"Failed to parse {f.filename}: {str(e)}")

    # If user explicitly uploaded only transaction files, clear old trade memory to trigger Scenario B
    if uploaded_transaction and not uploaded_trade:
        _LAST_TRADE_DF.pop(user_id, None)
        _LAST_TRADE_FILENAME.pop(user_id, None)

    results["missing_trade_history"] = (user_id not in _LAST_TRADE_DF) and (user_id in _LAST_TRANSACTION_DF)

    trade_df = _LAST_TRADE_DF.get(user_id)
    if trade_df is not None and "Market" in trade_df.columns:
        results["unresolved_symbols"] = find_unresolved_symbols(trade_df["Market"].tolist())
    else:
        results["unresolved_symbols"] = []

    return results

@router.get("/summary", response_model=PortfolioSummary)
def get_portfolio_summary(user: dict = Depends(get_current_user)):
    user_id = user.get("sub", "default")
    df, filename = get_or_load_trade_df(user_id)
    has_trans = user_id in _LAST_TRANSACTION_DF
    trans_filename = _LAST_TRANSACTION_FILENAME.get(user_id)
    missing_trade = (df is None) and has_trans

    if df is None:
        # Fallback empty summary
        return {
            "total_market_value_gbp": 0.0,
            "total_invested_cash": 0.0,
            "total_pnl_gbp": 0.0,
            "currency_allocation": {"usd_gbp": 0.0, "eur_gbp": 0.0, "gbp": 0.0, "total_gbp": 0.0},
            "positions": [],
            "source_file": None,
            "transaction_file": trans_filename,
            "trade_activities": [],
            "missing_trade_history": missing_trade,
            "data_quality": empty_data_quality(),
        }

    res = calculate_positions_from_df(df)
    res["source_file"] = filename
    res["transaction_file"] = trans_filename
    res["trade_activities"] = extract_trade_activities(df)
    res["missing_trade_history"] = False
    return res

@router.get("/waterfall", response_model=List[CashflowItem])
def get_cashflow_waterfall(user: dict = Depends(get_current_user)):
    user_id = user.get("sub", "default")
    df = _LAST_TRANSACTION_DF.get(user_id)
    # After a manual upload without a transaction statement, an empty list (rendered as —) is
    # the honest answer; don't substitute a statement from ~/Downloads the user didn't choose.
    if df is None and not _USER_MANUAL_UPLOAD.get(user_id):
        _, latest_trans = find_latest_download_files()
        if latest_trans and os.path.exists(latest_trans):
            try:
                df = pd.read_csv(latest_trans)
                _LAST_TRANSACTION_DF[user_id] = df
                _LAST_TRANSACTION_FILENAME[user_id] = os.path.basename(latest_trans)
            except Exception:
                pass

    if df is None:
        return []
    return calculate_cashflow_waterfall(df)

@router.post("/reset")
def reset_portfolio(user: dict = Depends(get_current_user)):
    """Reset loaded files and re-scan for latest files from ~/Downloads."""
    user_id = user.get("sub", "default")
    _LAST_TRADE_DF.pop(user_id, None)
    _LAST_TRANSACTION_DF.pop(user_id, None)
    _LAST_TRADE_FILENAME.pop(user_id, None)
    _LAST_TRANSACTION_FILENAME.pop(user_id, None)
    _USER_MANUAL_UPLOAD.pop(user_id, None)
    return {"status": "reset", "user_id": user_id}
