"""Ships log records to an OTLP endpoint (Grafana Cloud directly, or a local Alloy).

Enabled only when OTEL_EXPORTER_OTLP_ENDPOINT is set, so tests and a plain local run stay
offline. Values come from `settings` rather than the SDK's own env lookup, because pydantic
reads backend/.env into `settings` without exporting it to os.environ.

Records pass through the same redaction as stdout before they leave the process: the OTel
handler does not use our formatters, so without this a provider key in an exception message
would reach Grafana even though it is masked in the terminal.
"""
import atexit
import json
import logging
from typing import Dict, Optional
from urllib.parse import unquote

from backend.app.core.redaction import redact

_provider = None

# Attributes the SDK accepts are primitives or sequences of them; anything richer is
# JSON-encoded so it survives as one readable attribute instead of being dropped.
_PRIMITIVES = (str, bool, int, float)
_STANDARD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)


def parse_kv(raw: Optional[str]) -> Dict[str, str]:
    """`k1=v1,k2=v2` as used by OTEL_EXPORTER_OTLP_HEADERS and OTEL_RESOURCE_ATTRIBUTES."""
    out: Dict[str, str] = {}
    for part in (raw or "").split(","):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            out[key.strip()] = unquote(value.strip())
    return out


class RedactingOTelHandler(logging.Handler):
    """Wraps the SDK's LoggingHandler, handing it a redacted, flattened copy of each record."""

    def __init__(self, inner: logging.Handler) -> None:
        super().__init__()
        self._inner = inner

    def emit(self, record: logging.LogRecord) -> None:
        # The exporter logs its own failures; shipping those through itself would loop.
        if record.name.startswith("opentelemetry"):
            return
        try:
            fields = dict(record.__dict__)
            message = redact(record.getMessage()) or ""
            if record.exc_info:
                # Folded into the body so the stack is redacted too; the SDK would otherwise
                # format it itself, unredacted, into exception.stacktrace.
                message += "\n" + (redact(logging.Formatter().formatException(record.exc_info)) or "")
            fields.update(msg=message, args=None, exc_info=None, exc_text=None)
            for key, value in list(fields.items()):
                if key in _STANDARD_FIELDS:
                    continue
                if value is None:
                    fields.pop(key)
                elif not isinstance(value, _PRIMITIVES):
                    fields[key] = redact(json.dumps(value, default=str))
                elif isinstance(value, str):
                    fields[key] = redact(value)
            self._inner.emit(logging.makeLogRecord(fields))
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        self._inner.flush()


def build_otel_handler(settings) -> Optional[logging.Handler]:
    """A handler exporting to `{endpoint}/v1/logs`, or None when export is not configured."""
    global _provider
    endpoint = (settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip().rstrip("/")
    if not endpoint:
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
    except ImportError:
        logging.getLogger(__name__).warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but the OpenTelemetry packages are not "
            "installed; logs stay on stdout only. pip install -r backend/requirements.txt"
        )
        return None

    # A reload re-runs configuration; flush and close the previous pipeline first.
    if _provider is not None:
        _provider.shutdown()

    attributes = parse_kv(settings.OTEL_RESOURCE_ATTRIBUTES)
    attributes["service.name"] = settings.OTEL_SERVICE_NAME
    attributes.setdefault("deployment.environment", settings.ENVIRONMENT)

    _provider = LoggerProvider(resource=Resource.create(attributes))
    _provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(
                endpoint=f"{endpoint}/v1/logs",
                headers=parse_kv(settings.OTEL_EXPORTER_OTLP_HEADERS),
            )
        )
    )
    atexit.register(_provider.shutdown)
    return RedactingOTelHandler(LoggingHandler(logger_provider=_provider))
