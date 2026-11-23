from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from typing import List, Dict, Any, Optional, Tuple
import logging
import pandas as pd
import io
import os
import glob
import re
from datetime import datetime

from backend.app.services.portfolio_engine import calculate_positions_from_df, calculate_cashflow_waterfall, derive_cash_balance, empty_data_quality
from backend.app.services.realised_pnl import CORPORATE_ACTION
from backend.app.services.ticker_service import find_unresolved_symbols, load_ticker_mappings, resolve_ticker
from backend.app.schemas.portfolio import PortfolioSummary, CashflowItem, TradeActivityItem
from backend.app.core.security import get_current_user
from backend.app.core.diagnostics import log_data_quality
from backend.app.core.tracing import record_cache_hit, record_cache_miss, span

router = APIRouter(prefix="/trades", tags=["trades"])

logger = logging.getLogger(__name__)

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
    # The directory and the filenames stay off the span: the path contains the OS username and
    # the basename contains the broker account id.
    with span("trades.scan_downloads") as active:
        downloads_dir = os.path.expanduser('~/Downloads')
        if not os.path.isdir(downloads_dir):
            active.set_attribute("scan.candidates", 0)
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

        active.set_attribute("scan.candidates", len(found_files))
        active.set_attribute("scan.found_trade", latest_trade is not None)
        active.set_attribute("scan.found_transaction", latest_trans is not None)
        return latest_trade, latest_trans

UNKNOWN_FILL = "—"
_CURRENCY_SYMBOLS = {'USD': '$', 'GBP': '£', 'EUR': '€'}
# Consideration is rounded to 2dp, so a scaled Price never matches it exactly. 1% absorbs that
# rounding while staying far tighter than the 100x gap between a minor- and major-unit reading.
_FILL_SCALE_TOLERANCE = 0.01

def _to_amount(value: Any) -> float:
    """Coerce a statement cell to a float, tolerating currency symbols and thousands separators."""
    parsed = pd.to_numeric(re.sub(r'[£$€,\s]', '', str(value)), errors='coerce')
    return float(parsed) if pd.notnull(parsed) else float('nan')

def normalise_fill_price(price: Any, qty: Any, consideration: Any, currency: Any) -> str:
    """Render IG's `Price` cell as a per-share price carrying its own currency symbol.

    IG quotes `Price` in minor units (cents for USD, pence for GBX) with no marker, so 25808.0
    means $258.08. The row's own `Consideration` is gross and denominated in the same currency as
    `Price`, so `Consideration / Quantity` is a per-share reference that settles the 1x-vs-100x
    question without a network call. A row that cannot be settled that way returns `—`, because a
    bare figure here may be wrong by two orders of magnitude.
    """
    price = _to_amount(price)
    quantity = abs(_to_amount(qty))
    reference = abs(_to_amount(consideration))
    if not (price > 0 and quantity > 0 and reference > 0):
        return UNKNOWN_FILL

    per_share = reference / quantity
    scale = min((1.0, 0.01), key=lambda s: abs(price * s - per_share))
    scaled = price * scale
    if abs(scaled - per_share) > _FILL_SCALE_TOLERANCE * per_share:
        return UNKNOWN_FILL

    code = str(currency).strip().upper() if pd.notnull(currency) else ''
    symbol = _CURRENCY_SYMBOLS.get(code)
    return f"{symbol}{scaled:,.2f}" if symbol else f"{scaled:,.2f} {code}".strip()

def extract_trade_activities(df: pd.DataFrame, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Extract formatted trade activity records (newest first) from TradeHistory DataFrame.

    Dates are emitted as ISO `YYYY-MM-DD` so the client can filter by quarter/year.
    """
    # Outside the `try`, so the broad except that keeps the blotter from taking the whole
    # response down keeps its exact shape.
    with span("trades.activities", **{"activities.rows": len(df)}):
        return _trade_activities(df, limit)


def _trade_activities(df: pd.DataFrame, limit: Optional[int]) -> List[Dict[str, Any]]:
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
            cost = row.get('Cost/Proceeds', 0.0)
            parsed = row.get('ParsedDate')
            market = str(row.get('Market', ''))
            # The statement's own `Activity` column is the only thing that says a row was a
            # corporate action rather than an order the user placed -- 44 of this account's 339
            # rows are. `activity` deliberately stays BUY/SELL: a corp-action sell is still a
            # disposal, and the side filter, the cost-basis sum and the inspector chart all key
            # on it, so the distinction is carried alongside instead of overwriting it.
            is_corporate_action = str(row.get('Activity', '')).strip().upper() == CORPORATE_ACTION
            activities.append({
                'qty': abs(qty),
                'fill': normalise_fill_price(
                    row.get('Price'), qty, row.get('Consideration'), row.get('Currency')
                ),
                'value': f"£{abs(cost):,.2f}" if pd.notnull(cost) else "",
                'date': parsed.strftime('%Y-%m-%d') if pd.notnull(parsed) else str(row.get('TextDate', '')),
                'time': str(row.get('Time', '')),
                'activity': act,
                'is_corporate_action': is_corporate_action,
                'market': market,
                'ticker': resolve_ticker(market, ticker_map),
            })
        return activities
    except Exception:
        logger.exception("Could not build the trade activity list; the blotter will be empty")
        return []

def get_or_load_trade_df(user_id: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Get active trade df from memory or autoload the latest Tr*.csv from ~/Downloads."""
    # The span covers the in-memory check as well as the load, because the difference between
    # them is the question: a tenth of a millisecond on a hit against a glob plus a `read_csv`
    # on a miss.
    with span("trades.load_statement", **{"statement.kind": "trade"}) as active:
        df = _LAST_TRADE_DF.get(user_id)
        filename = _LAST_TRADE_FILENAME.get(user_id)
        if df is not None:
            record_cache_hit("trade_df")
            return df, filename

        # If the user performed a manual upload that lacked trade history,
        # do NOT auto-load from ~/Downloads behind the scenes.
        if _USER_MANUAL_UPLOAD.get(user_id) and user_id in _LAST_TRANSACTION_DF:
            return None, None

        # Counted here rather than above the early return: this request is about to glob and
        # parse, which is the cost a miss means. Declining to look is neither a hit nor a miss,
        # and leaves the cache absent from the span entirely.
        record_cache_miss("trade_df")
        # Search ~/Downloads
        latest_trade, latest_trans = find_latest_download_files()
        if latest_trade and os.path.exists(latest_trade):
            try:
                loaded_df = pd.read_csv(latest_trade)
                active.set_attribute("statement.rows", len(loaded_df))
                active.set_attribute("statement.columns", len(loaded_df.columns))
                _LAST_TRADE_DF[user_id] = loaded_df
                _LAST_TRADE_FILENAME[user_id] = os.path.basename(latest_trade)
                if latest_trans and os.path.exists(latest_trans) and user_id not in _LAST_TRANSACTION_DF:
                    try:
                        _LAST_TRANSACTION_DF[user_id] = pd.read_csv(latest_trans)
                        _LAST_TRANSACTION_FILENAME[user_id] = os.path.basename(latest_trans)
                    except Exception as e:
                        logger.warning(
                            "Could not autoload transaction statement %s: %s",
                            os.path.basename(latest_trans), e,
                        )
                logger.info("Autoloaded trade statement %s from ~/Downloads", os.path.basename(latest_trade))
                return loaded_df, os.path.basename(latest_trade)
            except Exception as e:
                active.set_attribute("statement.parse_failed", True)
                logger.warning("Could not autoload trade statement %s: %s", os.path.basename(latest_trade), e)
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
            logger.warning("Uploaded file %s could not be parsed: %s", f.filename, e)
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

    logger.info(
        "Statement upload: %d trade file(s), %d transaction file(s), %d error(s), %d unresolved symbol(s)",
        len(results["trade_files"]),
        len(results["transaction_files"]),
        len(results["errors"]),
        len(results["unresolved_symbols"]),
        extra={"event": "trades.uploaded"},
    )
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
            # The cash ledger stands on its own: a transaction statement with no trade history
            # still yields a balance.
            "cash_balance": derive_cash_balance(_LAST_TRANSACTION_DF.get(user_id)),
        }

    res = calculate_positions_from_df(df)
    res["source_file"] = filename
    res["transaction_file"] = trans_filename
    res["trade_activities"] = extract_trade_activities(df)
    res["missing_trade_history"] = False
    res["cash_balance"] = derive_cash_balance(_LAST_TRANSACTION_DF.get(user_id))
    log_data_quality(logger, "trades.summary", res.get("data_quality") or {})
    return res

def get_or_load_transaction_df(user_id: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Get the active transaction statement from memory or autoload the latest from ~/Downloads.

    The filename is returned, not just stored, because it carries the account it was exported for
    (`TransactionHistory-QX2B3-(...).csv`) and callers comparing it against a chosen account need
    to read it.
    """
    with span("trades.load_statement", **{"statement.kind": "transaction"}) as active:
        df = _LAST_TRANSACTION_DF.get(user_id)
        if df is not None:
            record_cache_hit("transaction_df")
            return df, _LAST_TRANSACTION_FILENAME.get(user_id)

        # After a manual upload without a transaction statement, having none is the honest
        # answer; don't substitute a statement from ~/Downloads the user didn't choose.
        if _USER_MANUAL_UPLOAD.get(user_id):
            return None, None

        record_cache_miss("transaction_df")
        _, latest_trans = find_latest_download_files()
        if latest_trans and os.path.exists(latest_trans):
            try:
                df = pd.read_csv(latest_trans)
                active.set_attribute("statement.rows", len(df))
                active.set_attribute("statement.columns", len(df.columns))
                _LAST_TRANSACTION_DF[user_id] = df
                _LAST_TRANSACTION_FILENAME[user_id] = os.path.basename(latest_trans)
                return df, _LAST_TRANSACTION_FILENAME[user_id]
            except Exception as e:
                active.set_attribute("statement.parse_failed", True)
                logger.warning(
                    "Could not autoload transaction statement %s: %s",
                    os.path.basename(latest_trans), e
                )
        return None, None

@router.get("/waterfall", response_model=List[CashflowItem])
def get_cashflow_waterfall(user: dict = Depends(get_current_user)):
    df, _ = get_or_load_transaction_df(user.get("sub", "default"))
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
    logger.info("Loaded statements reset", extra={"event": "trades.reset"})
    return {"status": "reset", "user_id": user_id}
