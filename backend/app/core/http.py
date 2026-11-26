"""An HTTP client that carries request correlation across a service boundary (P1).

Nothing calls this yet. It exists because P2 splits market-data out, and the moment one of our
services calls another, two things have to cross the wire or the split costs us the ability to
follow a single request:

- **`X-Request-ID`**, which the OpenTelemetry instrumentation will never send. It is this
  project's own correlation id, stamped on every log line by `RequestContextFilter`, and it is
  the only id that joins logs across services when tracing is off.
- **`traceparent`**, which the instrumentation *would* send -- but only when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set, because `otel_traces.instrument_app` returns before
  instrumenting anything when it is not. That is exactly the local-development case, so sending
  it here does not depend on an exporter being configured.

The id sent is always the one already in the request context, never a pass-through of an inbound
header: `middleware` validates `X-Request-ID` against a strict pattern before accepting it,
precisely because it is echoed into logs and responses, and re-reading the raw header here would
route around that check.
"""
import logging
import re
from typing import Optional

import requests
from requests.structures import CaseInsensitiveDict

from backend.app.core.request_context import get_request_id, get_trace

logger = logging.getLogger(__name__)

# No service-to-service call should ever hang a request thread waiting on a sibling. Overridable
# per call; the point is that the default is not "forever", which is what `requests` does.
DEFAULT_TIMEOUT = 10.0

_TRACEPARENT_VERSION = "00"
_SAMPLED_FLAGS = "01"

_HEX = re.compile(r"\A[0-9a-f]+\Z")


def _is_hex(value: Optional[str], length: int) -> bool:
    return bool(value) and len(value) == length and _HEX.match(value) is not None


def current_traceparent() -> Optional[str]:
    """This request's W3C `traceparent`, or None if there is no usable trace context.

    The live OpenTelemetry span wins when there is one, because that is the id Tempo will show.
    Without a tracer provider every span is non-recording and its context invalid, so the
    fallback is the trace ids parsed off the inbound Cloud Run header. Both halves are checked
    for shape before being sent: a malformed `traceparent` is worse than none, since a receiver
    is entitled to reject the header and start a new trace, silently breaking the join.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        pass
    else:
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            flags = _SAMPLED_FLAGS if context.trace_flags.sampled else "00"
            return "-".join((
                _TRACEPARENT_VERSION,
                trace.format_trace_id(context.trace_id),
                trace.format_span_id(context.span_id),
                flags,
            ))

    trace_id, span_id = get_trace()
    if _is_hex(trace_id, 32) and _is_hex(span_id, 16):
        return "-".join((_TRACEPARENT_VERSION, trace_id, span_id, _SAMPLED_FLAGS))
    return None


class PropagatingSession(requests.Session):
    """A `requests.Session` that adds correlation headers and a default timeout.

    Headers an explicit caller sets are left alone -- a caller forwarding a specific trace knows
    something this does not.
    """

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        super().__init__()
        self.timeout = timeout

    def request(self, method, url, **kwargs):  # type: ignore[override]
        kwargs.setdefault("timeout", self.timeout)
        headers = CaseInsensitiveDict(kwargs.get("headers") or {})

        request_id = get_request_id()
        if request_id and "X-Request-ID" not in headers:
            headers["X-Request-ID"] = request_id

        if "traceparent" not in headers:
            traceparent = current_traceparent()
            if traceparent:
                headers["traceparent"] = traceparent

        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)
