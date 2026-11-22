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
from contextlib import contextmanager
from typing import Iterator

from backend.app.core import otel_traces

_TRACER_NAME = "backend.app"


class _NoSpan:
    """Stands in for a span while tracing is off, so no caller needs a conditional."""

    def set_attribute(self, key, value) -> None:
        pass


_NO_SPAN = _NoSpan()


@contextmanager
def span(name: str, **attributes) -> Iterator[object]:
    """Open a child of whichever span is current -- the request span, normally."""
    provider = otel_traces._provider
    if provider is None:
        yield _NO_SPAN
        return
    with provider.get_tracer(_TRACER_NAME).start_as_current_span(
        name, attributes=attributes
    ) as active:
        yield active


def annotate(**attributes) -> None:
    """Attach attributes to the span already in progress, without opening one.

    For facts about a request that are not an operation in their own right -- a cache hit is
    the absence of work, and a span per lookup would dwarf the trace it sits in.
    """
    if otel_traces._provider is None:
        return
    from opentelemetry import trace
    trace.get_current_span().set_attributes(attributes)
