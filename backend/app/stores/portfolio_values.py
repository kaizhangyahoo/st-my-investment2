"""Store of historical portfolio values, owned by portfolio-api.

Two apps write this file. The legacy Streamlit app keys on bare broker account ids (`QX2B3`) and
the backend keys on `ig:<firebase sub>`, so every write is a read-merge-replace that touches only
its own key -- a whole-file write would delete the other app's accounts. A shared store does not
imply shared semantics: the two apps also differ on pence conversion, so a key written by one is
not interchangeable with a key written by the other, and the keys must never be summed.

Every top-level key is read as an account, which is why nothing else -- no metadata, no schema
version -- can be added at the top level of this file.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

from backend.app.core.config import settings
from backend.app.core.json_store import write_json_atomically
from backend.app.core.request_context import request_cache
from backend.app.core.tracing import span

logger = logging.getLogger(__name__)

KEY_PREFIX = "ig:"

# Slot in the per-request cache. The scope is the *request* and deliberately not a TTL: the
# legacy app writes this same path, so a copy outliving the request would widen the lost-update
# window the read-merge-write exists to close.
_VALUES_SLOT = "history.portfolio_values"

Values = Dict[str, Dict[str, float]]


def portfolio_key(user_id: str) -> str:
    return f"{KEY_PREFIX}{user_id}"


class PortfolioValuesStore:
    @property
    def path(self) -> str:
        return settings.PORTFOLIO_VALUES_FILE

    def read_from_disk(self) -> Values:
        """Parse the file, counting the open on a span.

        Spanned on the read itself, so the span count is the count of times the file was actually
        opened -- that is what made four repeats per request visible in the first place (KAN-69),
        and it is what `test_compute_path_spans.py` pins now that there are fewer. The path is not
        recorded: it is a log concern, and a span attribute is a different retention domain.
        """
        with span("history.cache_read") as active:
            path = self.path
            if not os.path.exists(path):
                active.set_attribute("cache.accounts", 0)
                active.set_attribute("cache.bytes", 0)
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
                active.set_attribute("cache.accounts", 0)
                active.set_attribute("cache.read_failed", True)
                return {}
            data = data if isinstance(data, dict) else {}
            active.set_attribute("cache.accounts", len(data))
            active.set_attribute("cache.bytes", os.path.getsize(path))
            return data

    def read(self, *, fresh: bool = False) -> Values:
        """The parsed file, read from disk once per request and shared from there.

        One compute request used to read and parse it four times (KAN-69): the pending-date
        filter, the merge, the response's points and the route's account list. Outside a request
        there is no scope and every call reads, as before.

        `fresh` reads from disk and does not consult the request's copy. `merge_key` needs it: the
        merge has to see whatever the legacy app committed while this request was off fetching
        prices, or it would write those keys back out of existence.
        """
        store = request_cache()
        if store is not None and not fresh:
            cached = store.get(_VALUES_SLOT)
            if cached is not None:
                return cached
        data = self.read_from_disk()
        if store is not None and not fresh:
            store[_VALUES_SLOT] = data
        return data

    def merge_key(self, key: str, new_values: Dict[str, float], replace: bool = False) -> None:
        """Re-read, merge only `key`, then atomically replace, so a concurrent writer keeps its keys.

        `replace` discards the key's existing dates first, so a forced recompute cannot leave
        behind a stale value for a date that has since become unvaluable.
        """
        if not new_values and not replace:
            return
        attributes = {"cache.days_written": len(new_values), "cache.replace": replace}
        # `key` is `ig:<firebase sub>`, so it stays out of the attributes: a user id belongs in a
        # log line, not on a span.
        with span("history.cache_write", **attributes) as active:
            path = self.path
            # Straight to disk, never this request's copy: the copy was taken before the price
            # fetches, and a legacy write landing in that window would be merged away.
            data = self.read(fresh=True)
            if replace:
                data[key] = {}
            data.setdefault(key, {}).update(new_values)
            try:
                write_json_atomically(path, data, prefix=".portfolio_values_")
            except OSError as e:
                active.set_attribute("cache.write_failed", True)
                logger.error(
                    "Could not persist history cache to %s: %s. This run's computed values are "
                    "lost and the next load recomputes them.",
                    path,
                    e,
                )
                return
            # The file now holds exactly `data`, so the rest of the request -- the response's
            # points, the route's account list -- needs no further read. Seeded only on success:
            # a failed write persisted nothing, and a later read has to fall back to the file.
            store = request_cache()
            if store is not None:
                store[_VALUES_SLOT] = data

    def series(self, key: str) -> List[Dict[str, Any]]:
        """The stored series for `key`, sorted by date. Used for the legacy T212 account keys too."""
        account = self.read().get(key, {})
        points = [{"date": d, "value": float(v)} for d, v in account.items() if v is not None]
        points.sort(key=lambda p: p["date"])
        return points

    def accounts(self) -> List[str]:
        """Every account key with at least one stored value."""
        return sorted(k for k, v in self.read().items() if isinstance(v, dict) and v)

    def default_account(self) -> Optional[str]:
        """The stored account holding the most values.

        One key per account, written by two different apps, so there is nothing to aggregate and
        no id worth hard-coding; the richest series is the only sensible thing to land on (KAN-46).
        """
        counts = sorted(
            ((key, len(v)) for key, v in self.read().items() if isinstance(v, dict) and v),
            key=lambda kv: (-kv[1], kv[0]),
        )
        return counts[0][0] if counts else None
