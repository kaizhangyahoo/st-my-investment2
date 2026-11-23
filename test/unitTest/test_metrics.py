"""Request metrics: off without an endpoint, and the HTTP duration series exist once on."""
import unittest
from types import SimpleNamespace

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
except ImportError:  # pragma: no cover
    TestClient = None

from backend.app.core import otel_metrics, otel_traces


def _settings(endpoint=None):
    return SimpleNamespace(
        OTEL_EXPORTER_OTLP_ENDPOINT=endpoint,
        OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf",
        OTEL_EXPORTER_OTLP_HEADERS=None,
        OTEL_RESOURCE_ATTRIBUTES="service.namespace=test",
        OTEL_SERVICE_NAME="test-svc",
        ENVIRONMENT="test",
    )


class TestMetricsDisabled(unittest.TestCase):
    def test_no_endpoint_means_no_provider(self):
        self.assertIsNone(otel_metrics.build_meter_provider(_settings()))


@unittest.skipIf(TestClient is None, "fastapi / opentelemetry sdk unavailable")
class TestHttpServerMetrics(unittest.TestCase):
    def setUp(self):
        self.reader = InMemoryMetricReader()
        app = FastAPI()

        @app.get("/api/ok")
        def ok():
            return {"ok": True}

        self.tracer_provider = otel_traces.instrument_app(
            app, _settings(), exporter=InMemorySpanExporter(), metric_reader=self.reader
        )
        self.client = TestClient(app)

    def tearDown(self):
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().uninstrument()
        self.tracer_provider.shutdown()
        otel_traces._provider = None
        otel_metrics._provider.shutdown()
        otel_metrics._provider = None

    def test_a_request_records_a_server_duration_metric(self):
        self.assertEqual(self.client.get("/api/ok").status_code, 200)
        data = self.reader.get_metrics_data()
        names = {
            metric.name
            for rm in data.resource_metrics
            for sm in rm.scope_metrics
            for metric in sm.metrics
        }
        self.assertTrue(
            names & {"http.server.duration", "http.server.request.duration"}, f"got {names}"
        )
        resource = data.resource_metrics[0].resource.attributes
        self.assertEqual(resource["service.name"], "test-svc")


if __name__ == "__main__":
    unittest.main()
