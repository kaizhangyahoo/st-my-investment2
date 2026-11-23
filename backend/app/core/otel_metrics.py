"""Ships request metrics to the same OTLP endpoint as logs and traces (Grafana Cloud -> Mimir).

Enabled only when OTEL_EXPORTER_OTLP_ENDPOINT is set, so tests and a plain local run stay
offline. The FastAPI and requests instrumentations emit the HTTP series once they are given
this provider (see otel_traces.instrument_app): server request duration by route and status,
and client request duration by remote host.
"""
import atexit
import logging

from backend.app.core.otel_logs import parse_kv

_provider = None

# Short enough that a Cloud Run instance scaling to zero loses little; shutdown also flushes.
EXPORT_INTERVAL_MS = 30_000


def build_meter_provider(settings, reader=None):
    """A configured MeterProvider, or None when export is not configured.

    `reader` is injectable so tests can collect metrics in memory without an endpoint.
    """
    global _provider
    endpoint = (settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip().rstrip("/")
    if reader is None and not endpoint:
        return None
    try:
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
        if reader is None:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=f"{endpoint}/v1/metrics",
                    headers=parse_kv(settings.OTEL_EXPORTER_OTLP_HEADERS),
                ),
                export_interval_millis=EXPORT_INTERVAL_MS,
            )
    except ImportError:
        logging.getLogger(__name__).warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but the OpenTelemetry metric packages are not "
            "installed; metrics are off. pip install -r backend/requirements.txt"
        )
        return None

    if _provider is not None:
        _provider.shutdown()

    attributes = parse_kv(settings.OTEL_RESOURCE_ATTRIBUTES)
    attributes["service.name"] = settings.OTEL_SERVICE_NAME
    attributes.setdefault("deployment.environment", settings.ENVIRONMENT)

    _provider = MeterProvider(resource=Resource.create(attributes), metric_readers=[reader])
    atexit.register(_provider.shutdown)
    return _provider
