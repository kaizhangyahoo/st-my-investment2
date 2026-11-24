"""Ships request traces to the same OTLP endpoint as the logs (Grafana Cloud -> Tempo).

Enabled only when OTEL_EXPORTER_OTLP_ENDPOINT is set, so tests and a plain local run stay
offline. Inbound W3C `traceparent` headers are continued, so a browser that mints its own
trace id (see frontend/src/services/logger.ts) lands in the same trace as the backend spans.
"""
import atexit
import logging
from typing import Optional

from backend.app.core.otel_logs import parse_kv
from backend.app.core.otel_metrics import build_meter_provider
from backend.app.core.redaction import redact

_provider = None

# Matched by `re.search` against the whole URL, over the comma-joined patterns -- so a bare
# `health` would also exclude a future /portfolio/health-check. Probes, the browser's own
# telemetry and the static bundle would each otherwise produce a trace per call.
EXCLUDED_URLS = ",".join((
    r"/health(\?|$)",
    r"/favicon\.ico(\?|$)",
    r"/telemetry/client-logs(\?|$)",
    r"/assets/",
))

# http.url is the old-semconv key this install emits; url.full is its opt-in replacement.
_URL_ATTRIBUTES = ("http.url", "url.full", "http.target")


def redact_span_url(span, _carrier=None) -> None:
    """Mask provider keys in a span's URL attributes.

    OpenTelemetry does call `redact_url` itself, but `util.http.PARAMS_TO_REDACT` is an
    AWS/GCP signature list that cannot be configured -- so TwelveData's `apikey` and EODHD's
    `api_token` reach Tempo in full without this. Wired as both the client and server request
    hook; both fire after the instrumentation has set its attributes, so this overwrites.
    """
    if not span.is_recording():
        return
    attributes = span.attributes or {}
    for key in _URL_ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, str):
            span.set_attribute(key, redact(value))


def build_tracer_provider(settings, exporter=None):
    """A configured TracerProvider, or None when export is not configured.

    `exporter` is injectable so tests can capture spans in memory without an endpoint.
    """
    global _provider
    endpoint = (settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip().rstrip("/")
    if exporter is None and not endpoint:
        return None
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        if exporter is None:
            # http/protobuf only, for the same reason the log exporter is. No resolve_protocol
            # call here: build_otel_handler already warned about a grpc request at startup, and
            # warning twice for one setting reads like two separate problems.
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(
                endpoint=f"{endpoint}/v1/traces",
                headers=parse_kv(settings.OTEL_EXPORTER_OTLP_HEADERS),
            )
            processor = BatchSpanProcessor(exporter)
        else:
            processor = SimpleSpanProcessor(exporter)
    except ImportError:
        logging.getLogger(__name__).warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but the OpenTelemetry trace packages are not "
            "installed; tracing is off. pip install -r backend/requirements.txt"
        )
        return None

    if _provider is not None:
        _provider.shutdown()

    attributes = parse_kv(settings.OTEL_RESOURCE_ATTRIBUTES)
    attributes["service.name"] = settings.OTEL_SERVICE_NAME
    attributes.setdefault("deployment.environment", settings.ENVIRONMENT)

    _provider = TracerProvider(resource=Resource.create(attributes))
    _provider.add_span_processor(processor)
    atexit.register(_provider.shutdown)
    return _provider


def instrument_app(app, settings, exporter=None, metric_reader=None) -> Optional[object]:
    """Traces every inbound request and every outbound `requests` call (Yahoo, TwelveData,
    EODHD, Firebase...), and records their HTTP duration metrics. Returns the tracer provider,
    or None when tracing is off."""
    provider = build_tracer_provider(settings, exporter)
    if provider is None:
        return None
    meter_provider = build_meter_provider(settings, metric_reader)
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        meter_provider=meter_provider,
        excluded_urls=EXCLUDED_URLS,
        server_request_hook=redact_span_url,
        # Without this each request also emits `http send` and `http receive` children: three
        # spans where one carries all the signal, against a metered trace ingest allowance.
        exclude_spans=["send", "receive"],
    )
    requests_instrumentor = RequestsInstrumentor()
    if requests_instrumentor.is_instrumented_by_opentelemetry:
        requests_instrumentor.uninstrument()
    requests_instrumentor.instrument(
        tracer_provider=provider, meter_provider=meter_provider, request_hook=redact_span_url
    )

    # Logs and traces share one switch, so configure_logging's "log export enabled" line would
    # otherwise be the only evidence either is live -- and it still prints when the trace
    # packages are missing. Announced after instrumentation, so it means traced, not merely built.
    endpoint = (settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip().rstrip("/")
    if endpoint:
        logging.getLogger("app.startup").info(
            "Grafana Cloud OTLP trace export enabled -> %s/v1/traces (service: %s)",
            endpoint,
            settings.OTEL_SERVICE_NAME,
        )
    return provider
