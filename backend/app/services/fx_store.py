"""Module-level access to the FX close store.

The implementation moved to `backend.app.stores.fx` in P1; these names stay because they are the
module boundary `market_service` and the market-data route already import, and one of them is
patched by name in the tests. P2 points those callers at the store object directly, when
market-data becomes its own service and owns this file.
"""
from typing import Optional

from backend.app.stores.fx import PAIRS, FxStore, Rates

_store = FxStore()


def read_rates() -> Rates:
    return _store.read()


def merge_rates(fetched: Rates) -> None:
    _store.merge(fetched)


def covered_through(stored: Optional[Rates] = None) -> Optional[str]:
    return _store.covered_through(stored)


def fetch_from(start_date: str, stored: Optional[Rates] = None) -> str:
    return _store.fetch_from(start_date, stored)
