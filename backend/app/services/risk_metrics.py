"""Risk and return statistics derived from a stored portfolio value series (KAN-27).

Pure functions over the `[{"date", "value"}]` shape `history_service.read_cached_series`
returns: no provider calls, no file access, nothing cached. The tiles these feed used to show
hardcoded figures, so every number here has to be traceable to the series or be null -- a null
renders as "unavailable" rather than as a plausible-looking placeholder (KAN-18, KAN-19).

Windows are cut from the *last stored date*, not from today, because a series that stops short
of today would otherwise report an empty 1M window for an account that simply has not been
recomputed yet. The client filters its chart by the `start_date` returned here so the tiles and
the curve can never describe different periods.
"""
from typing import Any, Dict, List, Optional

import pandas as pd

TIMEFRAME_MONTHS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12}
TIMEFRAMES = ["1M", "3M", "6M", "1Y", "ALL"]

# Trading days per year. Volatility is annualised from consecutive observations, which are
# business days with market holidays dropped, so 252 matches the sampling frequency.
_TRADING_DAYS_PER_YEAR = 252


def window(points: List[Dict[str, Any]], timeframe: str) -> List[Dict[str, Any]]:
    """The tail of `points` covering `timeframe`, measured back from the last stored date."""
    if timeframe == "ALL" or not points:
        return list(points)
    months = TIMEFRAME_MONTHS.get(timeframe)
    if months is None:
        return list(points)
    cutoff = pd.Timestamp(points[-1]["date"]) - pd.DateOffset(months=months)
    start = cutoff.strftime("%Y-%m-%d")
    return [p for p in points if p["date"] >= start]


def daily_returns(points: List[Dict[str, Any]]) -> List[float]:
    """Simple return between consecutive observations.

    Pairs spanning a holiday or a dropped date are treated as one period rather than scaled by
    the calendar gap: the series does not record how many sessions it skipped, and inventing a
    scaling factor would change the volatility figure without any data behind it.
    """
    returns = []
    for previous, current in zip(points, points[1:]):
        before = previous["value"]
        if before > 0:
            returns.append(current["value"] / before - 1.0)
    return returns


def max_drawdown_pct(points: List[Dict[str, Any]]) -> Optional[float]:
    """Worst peak-to-trough decline in the window, as a positive percentage of the peak."""
    if len(points) < 2:
        return None
    peak = None
    worst = 0.0
    for point in points:
        value = point["value"]
        if peak is None or value > peak:
            peak = value
        if peak and peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst * 100.0


def annualised_volatility_pct(points: List[Dict[str, Any]]) -> Optional[float]:
    """Annualised standard deviation of the daily returns, as a percentage."""
    returns = daily_returns(points)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return (variance**0.5) * (_TRADING_DAYS_PER_YEAR**0.5) * 100.0


def metrics_for(points: List[Dict[str, Any]], timeframe: str) -> Dict[str, Any]:
    """Every statistic for one window, with nulls where the window cannot support one."""
    sliced = window(points, timeframe)
    absolute: Optional[float] = None
    percent: Optional[float] = None
    if len(sliced) >= 2:
        first, last = sliced[0]["value"], sliced[-1]["value"]
        absolute = last - first
        if first != 0:
            percent = (absolute / first) * 100.0
    return {
        "timeframe": timeframe,
        "start_date": sliced[0]["date"] if sliced else None,
        "end_date": sliced[-1]["date"] if sliced else None,
        "trading_days": len(sliced),
        "cumulative_return_pct": percent,
        "cumulative_return_gbp": absolute,
        "max_drawdown_pct": max_drawdown_pct(sliced),
        "annualised_volatility_pct": annualised_volatility_pct(sliced),
        # Always null: an excess return needs a GBP risk-free rate and nothing here supplies
        # one. Substituting an assumed rate would put a figure on the tile that no fetched
        # data backs, so the tile reports it as unavailable instead.
        "sharpe_ratio": None,
    }


def all_windows(points: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {timeframe: metrics_for(points, timeframe) for timeframe in TIMEFRAMES}
