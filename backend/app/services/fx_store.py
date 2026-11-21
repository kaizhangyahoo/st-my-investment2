"""On-disk store of settled daily FX closes (KAN-55).

A past daily close never changes, which is what makes FX worth persisting where prices and
portfolio values are not: those have a "current" value that goes stale, this does not. The store
earns its keep twice over. It gives the unreachable-provider path something better than the
hardcoded constants -- the last real close instead of a guess -- and it shrinks the fetch, which
otherwise re-reads years of history on every process restart because the in-memory TTL cache does
not survive one.

Deliberately free of pandas and of any `services` import: `market_service` depends on this module,
and `history_service` depends on `market_service`, so a dependency the other way would be circular.

Kept separate from `user_portfolio_values.json` rather than added to it. That file's shape is fixed
by the legacy app, and `history_service.stored_accounts()` reads every top-level key as an account,
so a metadata section there would be listed as one.
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from backend.app.core.config import settings

PAIRS: Tuple[str, ...] = ("GBPUSD=X", "GBPEUR=X")

# How far back before the stored history a top-up fetch starts. Any window this wide contains a
# trading day, so "the provider returned nothing" stays a reliable failure signal -- asking only
# for the day after the last close would come back empty every Saturday. The overlap also lets a
# re-fetch correct a stored close, since the fetched value wins the merge.
_OVERLAP_DAYS = 7

Rates = Dict[str, Dict[str, float]]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _shift(iso_date: str, days: int) -> str:
    return (datetime.strptime(iso_date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def _clean(raw) -> Rates:
    """Only well-formed `{pair: {YYYY-MM-DD: number}}` entries survive.

    The file is a boundary -- it can be hand-edited or half-written by an older build -- and one
    bad entry must not cost us the rest of the history.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned: Rates = {}
    for pair, series in raw.items():
        if not isinstance(series, dict):
            continue
        dated = {}
        for day, rate in series.items():
            try:
                datetime.strptime(day, "%Y-%m-%d")
                value = float(rate)
            except (TypeError, ValueError):
                continue
            if value > 0:  # a zero or negative rate would silently produce nonsense valuations
                dated[day] = value
        if dated:
            cleaned[pair] = dated
    return cleaned


def read_rates() -> Rates:
    path = settings.FX_HISTORY_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return _clean(json.load(f))
    except (OSError, ValueError) as e:
        print(f"Could not read {path}: {e}. Treating the FX store as empty.")
        return {}


def merge_rates(fetched: Rates) -> None:
    """Add newly fetched closes, keeping everything already stored. Atomic, like the values file.

    Dates from today onward are dropped: Yahoo's last row is the in-progress bar, and storing it
    would serve an intraday snapshot tomorrow as though it were a settled close. Callers still get
    today's rate in memory -- it just does not become history.
    """
    today = _today()
    settled = {
        pair: {day: rate for day, rate in series.items() if day < today}
        for pair, series in _clean(fetched).items()
    }
    settled = {pair: series for pair, series in settled.items() if series}
    if not settled:
        return

    data = read_rates()
    for pair, series in settled.items():
        data.setdefault(pair, {}).update(series)

    path = settings.FX_HISTORY_FILE
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".fx_history_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({pair: dict(sorted(s.items())) for pair, s in sorted(data.items())}, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"Could not persist the FX store to {path}: {e}")
        if os.path.exists(tmp):
            os.unlink(tmp)


def covered_through(stored: Optional[Rates] = None) -> Optional[str]:
    """The last date every pair has a real close for, or None if any pair has none.

    Taken across all pairs rather than per pair because a valuation can hold both USD and EUR
    positions, and a date is only soundly valued if every cross it might need is real.
    """
    rates = read_rates() if stored is None else stored
    if any(not rates.get(pair) for pair in PAIRS):
        return None
    return min(max(rates[pair]) for pair in PAIRS)


def fetch_from(start_date: str, stored: Optional[Rates] = None) -> str:
    """The earliest date the provider still has to be asked for.

    Normally just the tail end of what is stored, which is what turns a years-long fetch into a
    one-week one. A caller asking for history older than anything stored needs the whole range
    instead, since closes cannot be filled backwards.

    Never later than the stored history ends, even when the caller only wants a recent window:
    leaving a hole in the middle of the store would be invisible afterwards, and `_fx_frames`
    forward-fills across holes exactly as it does across weekends.
    """
    rates = read_rates() if stored is None else stored
    covered = covered_through(rates)
    if covered is None:
        return start_date
    if start_date < max(min(rates[pair]) for pair in PAIRS):
        return start_date
    return _shift(covered, -_OVERLAP_DAYS)
