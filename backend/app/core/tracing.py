"""Manual spans for work the auto-instrumentation structurally cannot see.

`FastAPIInstrumentor` gives one server span per request and `RequestsInstrumentor` one client
span per HTTP call. Between them they show that three provider hosts were called; they cannot
show which tier rescued a ticker, or that an answer came from a cache and touched no provider
at all.

Both helpers are no-ops unless `otel_traces` installed a provider, so a service can be
annotated unconditionally and the offline suite stays silent. Reading the provider from
`otel_traces` rather than the global tracer provider is deliberate: `instrument_app` passes its
provider explicitly and never calls `set_tracer_provider`, so `trace.get_tracer` would hand
back a no-op tracer and these spans would vanish.
"""
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, Iterator, Optional

from backend.app.core import otel_traces

_TRACER_NAME = "backend.app"

# Cache lookups counted for the innermost open `span()`, flushed onto it as it closes. A
# ContextVar rather than a module global: the Yahoo fan-out runs its workers through
# `contextvars.copy_context()`, and the copy shares this very dict, so a worker's lookups reach
# the span that waited on it. `None` means nobody is counting -- the whole offline suite, and any
# cache reached with no span open.
_CACHE_COUNTS: ContextVar[Optional[Dict[str, Dict[str, int]]]] = ContextVar(
    "cache_counts", default=None
)
# `counts[name][counter] += 1` is not atomic and the fan-out shares the dict, so the increment
# takes a lock -- `TTLCache`'s own precedent.
_COUNTS_LOCK = threading.Lock()


class _NoSpan:
    """Stands in for a span while tracing is off, so no caller needs a conditional."""

    def set_attribute(self, key, value) -> None:
        pass


_NO_SPAN = _NoSpan()


def _tally() -> Dict[str, int]:
    return {"hits": 0, "misses": 0, "uncacheable": 0}


def record_cache_hit(name: str) -> None:
    """Count a lookup `name` answered itself."""
    _record(name, "hits")


def record_cache_miss(name: str) -> None:
    """Count a lookup `name` could not answer, so the work behind it ran."""
    _record(name, "misses")


def record_cache_uncacheable(name: str) -> None:
    """Count a result `name` declined to keep.

    Separates a provider failing every call -- so the key never fills -- from a merely cold
    cache (KAN-53). Both read as misses otherwise.
    """
    _record(name, "uncacheable")


def _record(name: str, counter: str) -> None:
    counts = _CACHE_COUNTS.get()
    if counts is None:
        return
    with _COUNTS_LOCK:
        counts.setdefault(name, _tally())[counter] += 1


def _flush(active, counts: Dict[str, Dict[str, int]]) -> None:
    """Write one key set per cache that was reached, namespaced by its name.

    `cache.<name>.hit` carries the same meaning for thirty lookups that it does for one -- every
    answer came from the cache -- so a single Grafana query works across every cache.
    """
    with _COUNTS_LOCK:
        tallies = {name: dict(tally) for name, tally in counts.items()}
    for name, tally in tallies.items():
        active.set_attribute(f"cache.{name}.hits", tally["hits"])
        active.set_attribute(f"cache.{name}.misses", tally["misses"])
        active.set_attribute(f"cache.{name}.hit", tally["misses"] == 0)
        if tally["uncacheable"]:
            active.set_attribute(f"cache.{name}.uncacheable", tally["uncacheable"])


def _merge_up(counts: Dict[str, Dict[str, int]]) -> None:
    parent = _CACHE_COUNTS.get()
    if parent is None:
        return
    with _COUNTS_LOCK:
        for name, tally in counts.items():
            into = parent.setdefault(name, _tally())
            for counter, value in tally.items():
                into[counter] += value


@contextmanager
def span(name: str, **attributes) -> Iterator[object]:
    """Open a child of whichever span is current -- the request span, normally.

    Cache lookups made in the body are counted and flushed on as `cache.<name>.*`. The counts are
    *inclusive*: a child reports its own and then merges them into its parent, so
    `history.compute` says what its whole subtree asked of every cache, which is what its
    duration already says. Summing one key across the spans of a trace therefore double-counts --
    as does summing duration.

    The flush runs inside the `with`, while the span is still recording: `set_attribute` on an
    ended span logs "Setting attribute on ended span." and drops the value. It runs in a
    `finally`, so a body that raised mid-loop still reports what it managed.
    """
    provider = otel_traces._provider
    if provider is None:
        yield _NO_SPAN
        return
    with provider.get_tracer(_TRACER_NAME).start_as_current_span(
        name, attributes=attributes
    ) as active:
        counts: Dict[str, Dict[str, int]] = {}
        token = _CACHE_COUNTS.set(counts)
        try:
            yield active
        finally:
            _CACHE_COUNTS.reset(token)
            _flush(active, counts)
            _merge_up(counts)


def annotate(**attributes) -> None:
    """Attach attributes to the span already in progress, without opening one.

    For facts about a request that are not an operation in their own right -- a cache hit is
    the absence of work, and a span per lookup would dwarf the trace it sits in.
    """
    if otel_traces._provider is None:
        return
    from opentelemetry import trace
    trace.get_current_span().set_attributes(attributes)


def event(name: str, **attributes) -> None:
    """Record a timestamped event on the span already in progress.

    For a thing that happened at a moment rather than a thing that took time: a degraded
    response is one event inside an otherwise ordinary request.

    Guarded on the provider rather than by adding `add_event` to `_NoSpan`, so that stub stays
    the minimum a `with span(...)` body needs and callers here never hold a span object.
    """
    if otel_traces._provider is None:
        return
    from opentelemetry import trace
    trace.get_current_span().add_event(name, attributes)
