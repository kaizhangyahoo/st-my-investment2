"""Historical portfolio valuation, ported from the legacy Streamlit implementation.

The reference is `rewrite_tab_1.py` (`calculate_portfolio_value_on_date` /
`get_portfolio_value_history`). Two deliberate departures from it:

1. Currency comes from Yahoo's quote currency, not the broker CSV's `Currency` column. Legacy
   divided every GBP-flagged row by 100, which is wrong for the LSE instruments that quote in
   pounds rather than pence. Yahoo reports "GBp" only when the close really is pence.
2. A holding in a currency we have no cross for invalidates the date instead of contributing
   zero. Legacy seeded `GBP_Value` with 0.0 and filled only USD/EUR/GBP, so an unexpected
   currency silently understated the total.

Both apps share `user_portfolio_values.json`, so its shape is fixed: a flat
`{key: {"YYYY-MM-DD": float}}`, one series per account. Legacy owns the bare broker account-id
keys ("QX2B3" is an IG account, not a Trading 212 one — the statement is
`TradeHistory-QX2B3-(...).csv`); this module writes `ig:<user_id>` keys. The keys are not all
the same person's and two of them can be the same account, so they must never be summed: that
mislabelling is what made a cross-account total look reasonable (KAN-46). Writes re-read and
merge before an atomic replace so a concurrent legacy run loses at most its own unflushed dates,
not the whole file.
"""
import logging
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backend.app.core.config import settings
from backend.app.services import fx_store
from backend.app.services.market_service import get_historical_fx, get_price_history
from backend.app.services.ticker_service import load_ticker_mappings, resolve_ticker

logger = logging.getLogger(__name__)

KEY_PREFIX = "ig:"

# Yahoo quote currency -> how to turn a close into GBP. "GBp" is pence, not a separate currency.
_FX_PAIR = {"USD": "GBPUSD=X", "EUR": "GBPEUR=X"}


def portfolio_key(user_id: str) -> str:
    return f"{KEY_PREFIX}{user_id}"


def _normalise_trades(df_trade_history: pd.DataFrame) -> pd.DataFrame:
    """Trade rows reduced to the three columns valuation needs, with tickers resolved.

    Dates are normalised to midnight so a trade counts on its own day, matching the legacy
    `Date <= target_date` comparison against a midnight-normalised target.
    """
    df = df_trade_history.copy()
    if "TextDate" in df.columns:
        # IG exports TextDate as DD-MM-YYYY; dayfirst is required there and wrong anywhere else,
        # since it would read an ISO "2024-01-02" as the 1st of February.
        df["Date"] = pd.to_datetime(df["TextDate"], errors="coerce", dayfirst=True)
    elif "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    else:
        return pd.DataFrame(columns=["Date", "Ticker", "Quantity"])

    ticker_map = load_ticker_mappings()
    df["Ticker"] = df["Market"].map(lambda name: resolve_ticker(name, ticker_map))
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")

    df = df.dropna(subset=["Date", "Ticker", "Quantity"])
    df["Date"] = df["Date"].dt.normalize()
    return df[["Date", "Ticker", "Quantity"]]


def _fx_frames(
    start_date: str, index: pd.DatetimeIndex
) -> Tuple[Dict[str, pd.Series], bool, Optional[pd.Timestamp]]:
    """GBP crosses forward-filled onto `index`, reproducing the legacy `Series.asof()` lookup.

    Also reports the last date every cross is backed by a real close, or None if none of them
    are. The ffill is the right answer for a market holiday, but past the end of the series it
    carries the last rate forward indefinitely and silently, so the caller needs to know where
    the real rates stop before it persists anything (KAN-55).
    """
    fx_dict, fx_fallback = get_historical_fx(start_date)
    aligned = {}
    ends = []
    for pair, series in fx_dict.items():
        s = pd.Series(series).sort_index()
        s.index = pd.to_datetime(s.index).normalize()
        s = s[~s.index.duplicated(keep="last")]
        if len(s):
            ends.append(s.index.max())
        aligned[pair] = s.reindex(s.index.union(index)).ffill().reindex(index)
    # A degraded feed with nothing in the store is the one case where the series are the
    # approximated constants rather than real closes, so their index says nothing about what is
    # backed: `get_historical_fx` only falls back once every stored rate has been exhausted, and
    # it stores every real close it fetches.
    approximated = fx_fallback and fx_store.covered_through() is None
    real_through = None if approximated or not ends else min(ends)
    return aligned, fx_fallback, real_through


def _price_frame(
    tickers: List[str], start_date: str
) -> Tuple[Dict[str, pd.Series], Dict[str, Optional[str]], List[str]]:
    """Per-ticker close series in native currency, plus each ticker's quote currency."""
    closes: Dict[str, pd.Series] = {}
    currencies: Dict[str, Optional[str]] = {}
    unpriced: List[str] = []
    for ticker in tickers:
        df, currency = get_price_history(ticker, start_date)
        if df.empty:
            unpriced.append(ticker)
            continue
        index = pd.DatetimeIndex(pd.to_datetime(df["Date"])).normalize()
        s = pd.Series(df["close"].values, index=index)
        closes[ticker] = s[~s.index.duplicated(keep="last")].sort_index()
        currencies[ticker] = currency
    return closes, currencies, unpriced


def _to_gbp(
    closes: Dict[str, pd.Series],
    currencies: Dict[str, Optional[str]],
    fx: Dict[str, pd.Series],
    index: pd.DatetimeIndex,
) -> Tuple[pd.DataFrame, List[Dict[str, str]]]:
    """Wide Date x Ticker frame of GBP closes. Unconvertible tickers are dropped, not zeroed."""
    gbp: Dict[str, pd.Series] = {}
    unconvertible: List[Dict[str, str]] = []
    for ticker, series in closes.items():
        aligned = series.reindex(index)
        currency = (currencies.get(ticker) or "").strip()
        if currency == "GBP":
            gbp[ticker] = aligned
        elif currency == "GBp":
            gbp[ticker] = aligned / 100.0
        elif currency in _FX_PAIR:
            rate = fx.get(_FX_PAIR[currency])
            gbp[ticker] = aligned / rate if rate is not None else pd.Series(float("nan"), index=index)
        else:
            unconvertible.append({"ticker": ticker, "currency": currency or "unknown"})
    frame = pd.DataFrame(gbp, index=index) if gbp else pd.DataFrame(index=index)
    return frame, unconvertible


def _holdings_frame(trades: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Signed quantity held per ticker as of each date in `index`."""
    pivot = trades.pivot_table(index="Date", columns="Ticker", values="Quantity", aggfunc="sum")
    combined = pivot.index.union(index)
    return pivot.reindex(combined).fillna(0.0).cumsum().reindex(index)


def _value_series(holdings: pd.DataFrame, prices_gbp: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """Total GBP value per date, plus a mask of dates a held position could not be priced.

    A date with no open positions is worth 0.0, as in legacy. A date where any open position
    lacks a close that day is invalid -- legacy matched the date exactly rather than carrying
    the last known price forward, and valuing a partial portfolio would understate the total.
    """
    prices = prices_gbp.reindex(columns=holdings.columns)
    held = holdings.fillna(0.0) != 0
    invalid = (held & prices.isna()).any(axis=1)
    values = (holdings.where(held, 0.0) * prices.fillna(0.0)).sum(axis=1)
    return values, invalid


def _fx_unbacked(
    holdings: pd.DataFrame,
    currencies: Dict[str, Optional[str]],
    real_through: Optional[pd.Timestamp],
) -> pd.Series:
    """Dates whose valuation would rest on an FX rate nobody quoted.

    Past the last real close the forward-filled rate is a reasonable number to *show* and a bad
    one to *store*: the shared file has no room to record that a value was approximated, and
    nothing ever recomputes a date already in it, so the estimate becomes permanent and
    indistinguishable from a real valuation (KAN-55). A date holding only GBP-quoted positions
    needs no rate and is unaffected.
    """
    needs_fx = [
        ticker
        for ticker, currency in currencies.items()
        if (currency or "").strip() in _FX_PAIR and ticker in holdings.columns
    ]
    if not needs_fx:
        return pd.Series(False, index=holdings.index)
    holds_fx = (holdings[needs_fx].fillna(0.0) != 0).any(axis=1)
    if real_through is None:
        return holds_fx
    return holds_fx & (holdings.index > real_through)


def _read_cache_file() -> Dict[str, Dict[str, float]]:
    path = settings.PORTFOLIO_VALUES_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning(
            "Could not read %s: %s. Treating the history cache as empty, so the whole "
            "series recomputes from scratch.",
            path,
            e,
        )
        return {}
    return data if isinstance(data, dict) else {}


def _merge_and_write(key: str, new_values: Dict[str, float], replace: bool = False) -> None:
    """Re-read, merge only `key`, then atomically replace, so a concurrent writer keeps its keys.

    `replace` discards the key's existing dates first, so a forced recompute cannot leave behind
    a stale value for a date that has since become unvaluable.
    """
    if not new_values and not replace:
        return
    path = settings.PORTFOLIO_VALUES_FILE
    data = _read_cache_file()
    if replace:
        data[key] = {}
    data.setdefault(key, {}).update(new_values)
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".portfolio_values_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        logger.error(
            "Could not persist history cache to %s: %s. This run's computed values are lost "
            "and the next load recomputes them.",
            path,
            e,
        )
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_cached_series(key: str) -> List[Dict[str, Any]]:
    """The stored series for `key`, sorted by date. Used for the legacy T212 account keys too."""
    account = _read_cache_file().get(key, {})
    points = [{"date": d, "value": float(v)} for d, v in account.items() if v is not None]
    points.sort(key=lambda p: p["date"])
    return points


def stored_accounts() -> List[str]:
    """Every account key with at least one stored value."""
    return sorted(k for k, v in _read_cache_file().items() if isinstance(v, dict) and v)


def default_account() -> Optional[str]:
    """The stored account holding the most values.

    One key per account, written by two different apps, so there is nothing to aggregate and no
    id worth hard-coding; the richest series is the only sensible thing to land on (KAN-46).
    """
    counts = sorted(
        ((key, len(v)) for key, v in _read_cache_file().items() if isinstance(v, dict) and v),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return counts[0][0] if counts else None


def is_behind(points: List[Dict[str, Any]], today: Optional[str] = None) -> bool:
    """Whether a series stops before today, i.e. has a tail that computing could extend.

    Only the tail counts. Every interior missing day in the stored accounts is a single
    isolated date -- a market holiday, not a gap -- so treating those as fillable would offer
    to recompute a series that is already complete.
    """
    end = pd.Timestamp(today) if today else pd.Timestamp.now().normalize()
    if not points:
        return True
    last = pd.Timestamp(points[-1]["date"])
    return last < end and len(pd.bdate_range(last, end)) > 1


def compute_history(
    df_trade_history: pd.DataFrame, key: str, force_recompute: bool = False
) -> Dict[str, Any]:
    """Historical GBP portfolio value for a trade history, computing only uncached dates."""
    empty_quality = {
        "degraded": False,
        "fx_fallback": False,
        "skipped_dates": 0,
        "fx_unbacked_dates": 0,
        "unpriced_tickers": [],
        "unconvertible": [],
    }
    trades = _normalise_trades(df_trade_history)
    if trades.empty:
        return {
            "points": read_cached_series(key),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "data_quality": empty_quality,
        }

    start_date = trades["Date"].min().strftime("%Y-%m-%d")
    closes, currencies, unpriced = _price_frame(sorted(trades["Ticker"].unique()), start_date)

    if not closes:
        quality = {**empty_quality, "degraded": True, "unpriced_tickers": unpriced}
        return {
            "points": read_cached_series(key),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "data_quality": quality,
        }

    all_dates = pd.DatetimeIndex(sorted(set().union(*(s.index for s in closes.values()))))
    trading_days = all_dates[all_dates >= trades["Date"].min()]

    cached = _read_cache_file().get(key, {}) if not force_recompute else {}
    pending = pd.DatetimeIndex([d for d in trading_days if d.strftime("%Y-%m-%d") not in cached])

    skipped = 0
    fx_unbacked = 0
    unconvertible: List[Dict[str, str]] = []
    fx_degraded = False
    if len(pending):
        fx, fx_degraded, fx_real_through = _fx_frames(start_date, pending)
        prices_gbp, unconvertible = _to_gbp(closes, currencies, fx, pending)
        holdings = _holdings_frame(trades, pending)
        values, invalid = _value_series(holdings, prices_gbp)
        skipped = int(invalid.sum())
        unbacked = _fx_unbacked(holdings, currencies, fx_real_through)
        fx_unbacked = int(unbacked.sum())
        fresh = {
            d.strftime("%Y-%m-%d"): float(v)
            for d, v in values[~(invalid | unbacked)].items()
            if pd.notna(v)
        }
        _merge_and_write(key, fresh, replace=force_recompute)

    # Withholding the unsound dates is what lets this flag mean something on a cache hit: a
    # stored series contains only dates valued on a real rate, so `False` is a statement about
    # the points being returned and not just about a request that recomputed nothing.
    points = read_cached_series(key)
    return {
        "points": points,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "data_quality": {
            "degraded": bool(unpriced or unconvertible or skipped or fx_degraded or fx_unbacked),
            "fx_fallback": bool(fx_degraded or fx_unbacked),
            "skipped_dates": skipped,
            "fx_unbacked_dates": fx_unbacked,
            "unpriced_tickers": sorted(unpriced),
            "unconvertible": unconvertible,
        },
    }
