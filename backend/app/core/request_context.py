"""Per-request correlation identifiers, carried in context vars.

Service-layer code never takes a request argument, so the ids are stashed here and pulled
back out by a logging filter. That keeps every log line in a request correlated without
changing a single service signature.
"""
import logging
import uuid
from contextvars import ContextVar
from typing import Any, Dict, NamedTuple, Optional, Tuple

_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_trace: ContextVar[Optional[str]] = ContextVar("trace", default=None)
_span: ContextVar[Optional[str]] = ContextVar("span", default=None)
# Scratch space for anything a request would otherwise re-derive, keyed by the deriving module.
# Deliberately one mutable dict rather than a ContextVar per value: a sync endpoint runs in a
# threadpool with a *copy* of this context, so a var set inside the endpoint is invisible to the
# rest of the request, while writes into this dict are shared.
_request_cache: ContextVar[Optional[Dict[str, Any]]] = ContextVar("request_cache", default=None)


class _Tokens(NamedTuple):
    request_id: object
    trace: object
    span: object
    cache: object


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def get_request_id() -> Optional[str]:
    return _request_id.get()


def get_trace() -> Tuple[Optional[str], Optional[str]]:
    return _trace.get(), _span.get()


def request_cache() -> Optional[Dict[str, Any]]:
    """This request's scratch dict, or None when no request is bound.

    None is not the same as an empty dict: it means "not inside a request", so a caller outside
    one -- a test, a script, a background task -- keeps its uncached behaviour rather than
    sharing a single process-wide store with every other caller.
    """
    return _request_cache.get()


def bind_request(request_id: str, trace: Optional[str] = None, span: Optional[str] = None) -> _Tokens:
    return _Tokens(
        _request_id.set(request_id),
        _trace.set(trace),
        _span.set(span),
        _request_cache.set({}),
    )


def reset_request(tokens: _Tokens) -> None:
    _request_id.reset(tokens.request_id)
    _trace.reset(tokens.trace)
    _span.reset(tokens.span)
    _request_cache.reset(tokens.cache)


def parse_cloud_trace(header: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse `X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1`, tolerating anything malformed.

    Google sends TRACE_ID as 32 hex digits but SPAN_ID as a *decimal* integer, while both W3C
    and Cloud Logging's `spanId` want 16 lowercase hex digits. An id in the wrong base joins to
    nothing, so the span half is converted rather than copied -- and anything that is not a
    64-bit decimal is dropped, since the header is client-settable and a mis-shaped id is worse
    than no id at all.
    """
    if not header:
        return None, None
    value = header.split(";", 1)[0].strip()
    if not value:
        return None, None
    trace, _, span = value.partition("/")
    trace = trace.strip()
    span = span.strip()
    if not trace:
        return None, None
    if not span.isdigit() or int(span) >= 2 ** 64:
        return trace, None
    return trace, format(int(span), "016x")


class RequestContextFilter(logging.Filter):
    """Stamps correlation ids onto every record, including uvicorn's and third parties'.

    Attached to the handler rather than a logger so records that never pass through an
    app logger still get stamped.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        # The active span wins over the inbound Cloud Run header, and not the other way round:
        # a span only ever reaches Tempo under its OTel ids, so a line stamped with the
        # header's id would not join to it. Cloud Run always sends that header, so the wrong
        # order breaks joining in production exclusively -- every local test still passes.
        trace_id, span_id = _otel_ids()
        if trace_id is None:
            trace_id, span_id = _trace.get(), _span.get()
        record.trace_id = trace_id
        record.span_id = span_id
        return True


def _otel_ids() -> Tuple[Optional[str], Optional[str]]:
    """The active OpenTelemetry span's ids, so local (non-Cloud Run) log lines carry the
    same trace id that Tempo shows."""
    try:
        from opentelemetry import trace
    except ImportError:
        return None, None
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None, None
    return trace.format_trace_id(ctx.trace_id), trace.format_span_id(ctx.span_id)
