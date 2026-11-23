"""Request correlation and the access log.

Written as raw ASGI rather than BaseHTTPMiddleware for two reasons: BaseHTTPMiddleware runs
its dispatch in a separate task, so context vars set there are not reliably visible inside
the endpoint; and it buffers the response body, which would penalise the StaticFiles mount.
"""
import json
import logging
import re
import time
import traceback
from typing import Dict

from backend.app.core.redaction import redact
from backend.app.core.request_context import (
    bind_request,
    new_request_id,
    parse_cloud_trace,
    reset_request,
)

logger = logging.getLogger("app.access")

# Health probes and static asset fetches would swamp the log without adding signal.
_SILENT_PATHS = frozenset({"/health", "/favicon.ico"})

# An inbound id is echoed into a response header and every log line, so anything outside this
# shape is replaced rather than trusted (log injection, header splitting, unbounded length).
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def error_detail(scope) -> str:
    """Why the request was rejected, as recorded by the exception handlers, or ""."""
    state = scope.get("state")
    return str(state.get("error_detail", "")) if isinstance(state, dict) else ""


def _headers(scope) -> Dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def record_span_exception(exc: BaseException) -> None:
    """Attach the traceback to the active trace span, if tracing is on.

    OpenTelemetry's own ExceptionHandlerMiddleware wraps *outside* this middleware, so it never
    sees an exception handled here -- the span would reach Tempo marked ERROR by its 500 status
    with no stack on it. The message and stacktrace are redacted like every other sink: a
    `requests` error repr embeds the full URL, provider key included.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        return
    trace.get_current_span().record_exception(
        exc,
        attributes={
            "exception.message": redact(str(exc)),
            "exception.stacktrace": redact("".join(traceback.format_exception(exc))),
        },
    )


class RequestContextMiddleware:
    def __init__(self, app, api_prefix: str = "/api") -> None:
        self.app = app
        self.api_prefix = api_prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        trace, span = parse_cloud_trace(headers.get("x-cloud-trace-context"))
        inbound = headers.get("x-request-id", "")
        request_id = inbound if _VALID_REQUEST_ID.match(inbound) else new_request_id()

        path = scope.get("path", "")
        should_log = path not in _SILENT_PATHS and path.startswith(self.api_prefix)

        status_holder = {"status": 0, "started": False}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                status_holder["started"] = True
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [
                    (b"x-request-id", request_id.encode("latin-1"))
                ]
            await send(message)

        tokens = bind_request(request_id, trace, span)
        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            # Handled here rather than by an app-level Exception handler: Starlette runs those
            # in ServerErrorMiddleware, outside this one, after the request id is unbound --
            # so the 500 a user quotes would carry no id. The error is logged with it bound.
            logger.exception(
                "Unhandled error serving %s %s; the caller receives a 500",
                scope.get("method", ""),
                scope.get("path", ""),
            )
            record_span_exception(exc)
            if should_log:
                self._log(scope, headers, 500, time.perf_counter() - started)
            if status_holder["started"]:
                raise  # Too late to send a clean 500; let the server close the connection.
            body = json.dumps({"detail": "Internal server error", "request_id": request_id}).encode()
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", request_id.encode("latin-1")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
        else:
            if should_log:
                self._log(scope, headers, status_holder["status"], time.perf_counter() - started)
        finally:
            reset_request(tokens)

    def _log(self, scope, headers: Dict[str, str], status: int, elapsed: float) -> None:
        client = scope.get("client")
        http_request = {
            "requestMethod": scope.get("method", ""),
            # Path only. A query string can carry a provider key, and the redactor is a
            # safety net rather than a licence to log one.
            "requestUrl": scope.get("path", ""),
            "status": status,
            # A duration string, because that is the only form Cloud Logging parses here.
            # The numeric sibling a latency panel needs goes in `extra` below, outside this
            # dict -- these field names are Cloud Logging's and will not take an extra one.
            "latency": f"{elapsed:.3f}s",
            "userAgent": headers.get("user-agent", ""),
            "remoteIp": client[0] if client else "",
        }
        level = logging.INFO
        if status >= 500:
            level = logging.ERROR
        elif status >= 400:
            level = logging.WARNING
        detail = error_detail(scope) if status >= 400 else ""
        logger.log(
            level,
            "%s %s -> %s in %.0fms%s",
            http_request["requestMethod"],
            http_request["requestUrl"],
            status,
            elapsed * 1000,
            f" ({detail})" if detail else "",
            extra={"http_request": http_request, "duration_ms": round(elapsed * 1000, 1)},
        )
