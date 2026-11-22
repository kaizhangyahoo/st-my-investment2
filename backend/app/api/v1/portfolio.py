from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import logging
import pandas as pd
from backend.app.schemas.portfolio import (
    BenchmarkResponse,
    CashflowItem,
    MatchedBenchmarkResponse,
    PortfolioHistoryResponse,
    PortfolioMetricsResponse,
    PortfolioSummary,
)
from backend.app.core.security import get_current_user
from backend.app.core.diagnostics import log_data_quality
from backend.app.services import history_service, realised_pnl, risk_metrics
from backend.app.services.benchmark_service import deposit_matched_series
from backend.app.services.market_service import get_price_history
from backend.app.services.portfolio_engine import external_cashflows
from backend.app.api.v1.trades import get_or_load_trade_df, get_or_load_transaction_df

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

logger = logging.getLogger(__name__)

# Withheld-reason codes turned into something a user can act on. The codes themselves are an
# internal vocabulary shared by the engine and the benchmark service; the banner shows this text.
WITHHELD_MESSAGES = {
    "no_ledger": "the transaction statement has no readable deposit history",
    "unreadable_amounts": "some amounts in the transaction statement could not be read",
    "non_gbp": "the transaction statement mixes currencies, and it carries no rate to convert with",
    "undated": "the transaction statement has no column that dates every row",
    "partial_window": (
        "the transaction statement starts after the account did, so the early deposits are "
        "missing and the comparison would flatter the portfolio"
    ),
    "non_gbp_quote": "it is not quoted in GBP, so matching it would need a daily FX series",
    "no_closes": "no closes were returned for it",
    "no_cashflows": "no deposits were found to match",
}

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
        log_data_quality(logger, "portfolio.history.compute", result.get("data_quality") or {})
        logger.info(
            "History computed: %d point(s) stored (refresh=%s)",
            len(result.get("points") or []),
            refresh,
            extra={"event": "portfolio.history.computed"},
        )
    return {**result, "accounts": history_service.stored_accounts(), "account_id": key}

@router.get("/metrics", response_model=PortfolioMetricsResponse)
def get_metrics(
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Risk, return and closed-trade statistics per timeframe (KAN-27, KAN-52).

    Separate from `/history` so the account's series is fetched once and the tiles can switch
    windows without another request. The account is resolved exactly as `/history` resolves it,
    so both describe the same series.

    `windows` comes from the stored value series; `realised` comes from the trade statement, which
    is the only thing that knows what a position cost. Both are keyed by timeframe, but each
    reports its own bounds, because the two sources do not end on the same date.
    """
    key = account_id or history_service.default_account() or history_service.portfolio_key(
        user.get("sub", "default")
    )
    points = history_service.read_cached_series(key)
    df, source_file = get_or_load_trade_df(user.get("sub", "default"))
    if df is None:
        realised: Dict[str, Any] = realised_pnl.all_windows([])
        coverage: Dict[str, Any] = {
            "unavailable_reason": "No trade statement loaded, so no disposal can be priced"
        }
    else:
        book = realised_pnl.compute_disposals(df)
        realised = realised_pnl.all_windows(book["disposals"])
        coverage = {
            "source_file": source_file,
            "corporate_action_rows": book["corporate_action_rows"],
            "corporate_action_cash_gbp": book["corporate_action_cash_gbp"],
            "excluded_disposals": book["excluded_disposals"],
            "excluded_tickers": book["excluded_tickers"],
        }
    return {
        "account_id": key,
        "windows": risk_metrics.all_windows(points),
        "realised": realised,
        "realised_coverage": coverage,
    }

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
        logger.warning("No benchmark closes for %s since %s; the overlay is unavailable", symbol, start_date)
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

@router.get("/benchmark/matched", response_model=MatchedBenchmarkResponse)
def get_matched_benchmark(
    symbol: str = "VUSA.L",
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """A comparison line fed by the same deposits as the portfolio (KAN-58).

    `/benchmark` returns raw closes for the client to scale onto the curve's opening value, which
    silently means "one lump sum invested on day one" -- on the reference account that is GBP 835
    against GBP 94,633 of real deposits, so the chart read as a 100x outperformance where the
    truth is x2.65 against x2.02. This endpoint instead buys the index with each deposit as it
    arrived, which is the comparison the chart looked like it was already making.

    Returned already in GBP, so these values do not get rebased: the per-window rescaling that
    `/benchmark` relies on is the second half of the same fault, and absolute values are what make
    a short timeframe mean the same thing as a long one.
    """
    key = account_id or history_service.default_account() or history_service.portfolio_key(
        user.get("sub", "default")
    )
    withheld = {"symbol": symbol, "currency": None, "points": []}

    df, source_file = get_or_load_transaction_df(user.get("sub", "default"))
    if df is None:
        return {**withheld, "unavailable_reason": "No transaction statement is loaded, so there are no deposits to match"}

    # The statement is the caller's own and names the account it was exported for, while `key`
    # selects a stored value series. Charting one account's deposits against another's curve would
    # be wrong by the whole difference between them, and nothing on screen would say so.
    if not source_file or key not in source_file:
        return {
            **withheld,
            "unavailable_reason": (
                f"The loaded statement ({source_file or 'an upload with no account in its name'}) "
                f"is not the one for account {key}, so its deposits are not this curve's"
            ),
        }

    flows = external_cashflows(df)
    if "withheld_reason" in flows:
        reason = WITHHELD_MESSAGES[flows["withheld_reason"]]
        return {**withheld, "unavailable_reason": f"No deposit-matched comparison: {reason}"}
    if not flows["cashflows"]:
        return {**withheld, "unavailable_reason": f"No deposits found in {source_file}"}

    # From the first deposit rather than the chart's window start: closes before the earliest
    # deposit are irrelevant, and closes after a later window start would lose the early units.
    closes, currency = get_price_history(symbol, flows["cashflows"][0]["date"])
    series = deposit_matched_series(closes, currency, flows["cashflows"])
    if "withheld_reason" in series:
        reason = WITHHELD_MESSAGES[series["withheld_reason"]]
        return {
            **withheld,
            "currency": currency,
            "unavailable_reason": f"No comparison line for {symbol}: {reason}",
        }
    return {"symbol": symbol, "currency": currency, **series}

