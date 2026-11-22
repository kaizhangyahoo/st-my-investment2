"""Per-request correlation identifiers, carried in context vars.

Service-layer code never takes a request argument, so the ids are stashed here and pulled
back out by a logging filter. That keeps every log line in a request correlated without
changing a single service signature.
"""
import logging
import uuid
from contextvars import ContextVar
from typing import NamedTuple, Optional, Tuple

_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_trace: ContextVar[Optional[str]] = ContextVar("trace", default=None)
_span: ContextVar[Optional[str]] = ContextVar("span", default=None)


class _Tokens(NamedTuple):
    request_id: object
    trace: object
    span: object


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def get_request_id() -> Optional[str]:
    return _request_id.get()


def get_trace() -> Tuple[Optional[str], Optional[str]]:
    return _trace.get(), _span.get()


def bind_request(request_id: str, trace: Optional[str] = None, span: Optional[str] = None) -> _Tokens:
    return _Tokens(_request_id.set(request_id), _trace.set(trace), _span.set(span))


def reset_request(tokens: _Tokens) -> None:
    _request_id.reset(tokens.request_id)
    _trace.reset(tokens.trace)
    _span.reset(tokens.span)


def parse_cloud_trace(header: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse `X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1`, tolerating anything malformed."""
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
    return trace, (span or None)


class RequestContextFilter(logging.Filter):
    """Stamps correlation ids onto every record, including uvicorn's and third parties'.

    Attached to the handler rather than a logger so records that never pass through an
    app logger still get stamped.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.trace = _trace.get()
        record.span = _span.get()
        return True
