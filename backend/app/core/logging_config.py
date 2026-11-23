"""Logging setup: JSON on stdout under Cloud Run, readable text locally.

Cloud Run parses a single-line JSON object on stdout into a structured entry, so severity
filtering and trace correlation need no client library and no extra dependency.

All application-supplied dimensions are nested under `context` so nothing an app (or a
browser posting to the telemetry route) can set will ever collide with a reserved Cloud
Logging key such as `severity` or `httpRequest`.
"""
import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional

from backend.app.core.config import settings
from backend.app.core.otel_logs import build_otel_handler
from backend.app.core.redaction import collect_secret_literals, redact, set_secret_literals
from backend.app.core.request_context import RequestContextFilter

# Keys LogRecord always carries; anything else an app passes via `extra` is a custom dimension.
_RESERVED = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info", "taskName",
    "thread", "threadName", "request_id", "trace_id", "span_id", "http_request",
})

_SEVERITY = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


def _redact_value(value: Any) -> Any:
    """Redact a custom dimension, which is rarely a flat string.

    `log_data_quality` hands in `failures`, a list of `{"ticker", "provider", "reason"}` whose
    reason is `str(e)` on a `requests` error -- the whole URL, `apikey=` included. Redacting
    only the message would publish that key on every provider outage.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(v) for v in value]
    return value


def _custom_dimensions(record: logging.LogRecord) -> Dict[str, Any]:
    return {
        k: _redact_value(v) for k, v in record.__dict__.items()
        if k not in _RESERVED and not k.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """Emits the Cloud Logging structured-log contract as one line of JSON."""

    def __init__(self, project_id: Optional[str] = None) -> None:
        super().__init__()
        self._project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "severity": _SEVERITY.get(record.levelname, "DEFAULT"),
            "message": redact(record.getMessage()),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "logger": record.name,
        }

        trace_id = getattr(record, "trace_id", None)
        # A bare trace id is not useful to Cloud Logging, and a malformed resource name is
        # worse than none, so the field is omitted unless the project is known.
        if trace_id and self._project_id:
            payload["logging.googleapis.com/trace"] = (
                f"projects/{self._project_id}/traces/{trace_id}"
            )
            span_id = getattr(record, "span_id", None)
            if span_id:
                payload["logging.googleapis.com/spanId"] = span_id

        payload["logging.googleapis.com/sourceLocation"] = {
            "file": record.pathname,
            "line": str(record.lineno),
            "function": record.funcName,
        }

        http_request = getattr(record, "http_request", None)
        if http_request:
            payload["httpRequest"] = http_request

        context = _custom_dimensions(record)
        request_id = getattr(record, "request_id", None)
        if request_id:
            context["request_id"] = request_id
        if context:
            payload["context"] = context

        if record.exc_info:
            payload["stack_trace"] = redact(self.formatException(record.exc_info))
        if record.stack_info:
            payload["context"] = {**payload.get("context", {}), "stack": redact(record.stack_info)}

        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Terminal-friendly single line, with the request id inline so it stays greppable."""

    def format(self, record: logging.LogRecord) -> str:
        stamp = time.strftime("%H:%M:%S", time.localtime(record.created))
        request_id = getattr(record, "request_id", None)
        prefix = f"{stamp} {record.levelname:<8} {record.name}"
        if request_id:
            prefix += f" [req={request_id}]"
        line = f"{prefix} {redact(record.getMessage())}"

        context = _custom_dimensions(record)
        if context:
            line += "  " + " ".join(f"{k}={v}" for k, v in sorted(context.items()))
        if record.exc_info:
            line += "\n" + (redact(self.formatException(record.exc_info)) or "")
        return line


def _use_json() -> bool:
    configured = (settings.LOG_FORMAT or "auto").strip().lower()
    if configured == "json":
        return True
    if configured == "text":
        return False
    # K_SERVICE is set by Cloud Run and absent locally -- the convention this repo already
    # uses in rewrite_login.py.
    return os.environ.get("K_SERVICE") is not None


def configure_logging() -> None:
    """Install one stdout handler on the root logger. Safe to call repeatedly.

    basicConfig is deliberately avoided: it is a no-op once uvicorn has installed its own
    handlers, which it does before application import under some run modes.
    """
    set_secret_literals(collect_secret_literals(settings))

    root = logging.getLogger()
    # Drop only handlers this function installed, so a reload does not stack duplicates and
    # a host application's own handlers survive.
    for existing in list(root.handlers):
        if getattr(existing, "_pa_owned", False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler._pa_owned = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter(settings.GCP_PROJECT_ID) if _use_json() else TextFormatter())
    handler.addFilter(RequestContextFilter())

    level = getattr(logging, (settings.LOG_LEVEL or "INFO").strip().upper(), logging.INFO)
    root.addHandler(handler)
    root.setLevel(level)

    otel = build_otel_handler(settings)
    startup_logger = logging.getLogger("app.startup")
    if otel is not None:
        otel._pa_owned = True  # type: ignore[attr-defined]
        otel.addFilter(RequestContextFilter())
        root.addHandler(otel)
        startup_logger.info(
            "Grafana Cloud OTLP log export enabled -> %s (service: %s, protocol: %s)",
            settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            settings.OTEL_SERVICE_NAME,
            # settings.OTEL_EXPORTER_OTLP_PROTOCOL,
            otel._pa_protocol, # type: ignore[attr-defined]
        )
    elif settings.OTEL_EXPORTER_OTLP_ENDPOINT or settings.OTEL_EXPORTER_OTLP_HEADERS:
        # Configured and still not exporting, which `build_otel_handler` has already explained
        # in detail. Said again here because the startup block is the one place an operator
        # reads to answer "is this shipping logs?", and until now that question had no answer
        # in exactly the case where it matters: silence read identically to healthy.
        startup_logger.warning(
            "OTLP log export is configured but inactive; logs stay on stdout only. The "
            "preceding line from the exporter setup says why."
        )
    else:
        startup_logger.info("OTLP log export is inactive (local stdout logging only)")

    # The access line is re-emitted by our own middleware with latency and a request id, so
    # uvicorn's version would only duplicate it. Startup/shutdown errors are still wanted,
    # so uvicorn.error keeps propagating and gets reformatted by our handler.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False

    error = logging.getLogger("uvicorn.error")
    error.handlers = []
    error.propagate = True

    # HTTP client libraries log a line per request at INFO, which would double every outbound
    # provider call and every TestClient call. Their warnings are still wanted.
    for noisy in ("httpx", "httpx2", "httpcore", "urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
