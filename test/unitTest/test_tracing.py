"""Request tracing: off without an endpoint, continues a browser traceparent, links logs,
and never carries a provider key into a span attribute."""
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

try:
    import requests
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
except ImportError:  # pragma: no cover
    TestClient = None

from backend.app.core import otel_traces
from backend.app.core.request_context import RequestContextFilter


def _settings(endpoint=None):
    return SimpleNamespace(
        OTEL_EXPORTER_OTLP_ENDPOINT=endpoint,
        OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf",
        OTEL_EXPORTER_OTLP_HEADERS=None,
        OTEL_RESOURCE_ATTRIBUTES="service.namespace=test",
        OTEL_SERVICE_NAME="test-svc",
        ENVIRONMENT="test",
    )


def _adapter_returns_200(self, request, **kwargs):
    """Stands in for the transport so an outbound call reaches the span hook without a socket."""
    response = requests.Response()
    response.status_code = 200
    response.url = request.url
    response.request = request
    response._content = b"{}"
    return response


class TestTracingDisabled(unittest.TestCase):
    def test_no_endpoint_means_no_provider(self):
        self.assertIsNone(otel_traces.build_tracer_provider(_settings()))

    def test_no_endpoint_leaves_the_app_uninstrumented(self):
        app = SimpleNamespace()
        with mock.patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app") as inst:
            self.assertIsNone(otel_traces.instrument_app(app, _settings()))
        inst.assert_not_called()


@unittest.skipIf(TestClient is None, "fastapi / opentelemetry sdk unavailable")
class TestRequestSpans(unittest.TestCase):
    TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"

    def setUp(self):
        self.exporter = InMemorySpanExporter()
        app = FastAPI()
        self.seen = {}

        @app.get("/api/ok")
        def ok():
            record = logging.LogRecord("t", logging.INFO, "", 0, "m", None, None)
            RequestContextFilter().filter(record)
            self.seen["trace"] = record.trace
            return {"ok": True}

        self.provider = otel_traces.instrument_app(app, _settings(), exporter=self.exporter)
        self.client = TestClient(app)

    def tearDown(self):
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().uninstrument()
        # A successful build leaves the provider and its atexit hook in a module global.
        self.provider.shutdown()
        otel_traces._provider = None

    def test_a_browser_traceparent_is_continued_and_stamped_on_logs(self):
        res = self.client.get(
            "/api/ok", headers={"traceparent": f"00-{self.TRACE_ID}-00f067aa0ba902b7-01"}
        )
        self.assertEqual(res.status_code, 200)
        spans = self.exporter.get_finished_spans()
        # One span, not three: `http send` and `http receive` children are excluded.
        self.assertEqual(len(spans), 1)
        self.assertEqual(format(spans[0].context.trace_id, "032x"), self.TRACE_ID)
        self.assertEqual(self.seen["trace"], self.TRACE_ID)
        self.assertEqual(spans[0].resource.attributes["service.name"], "test-svc")

    def test_a_provider_key_in_an_outbound_url_never_reaches_a_span(self):
        url = "https://api.twelvedata.invalid/time_series?symbol=AAPL&apikey=SUPERSECRET_TD_KEY"
        with mock.patch.object(requests.adapters.HTTPAdapter, "send", _adapter_returns_200):
            requests.get(url, timeout=5)
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        recorded = spans[0].attributes["http.url"]
        self.assertNotIn("SUPERSECRET_TD_KEY", recorded)
        self.assertIn("apikey=[redacted]", recorded)

    def test_probes_assets_and_browser_telemetry_are_not_traced(self):
        for path in (
            "/health",
            "/favicon.ico",
            "/api/v1/telemetry/client-logs",
            "/assets/index-D38HPXqq.js",
        ):
            with self.subTest(path=path):
                self.exporter.clear()
                self.client.get(path)
                self.assertEqual(len(self.exporter.get_finished_spans()), 0)

    def test_a_path_merely_containing_an_excluded_word_is_still_traced(self):
        # The patterns are matched with re.search, so an unanchored `health` would swallow this.
        self.client.get("/api/portfolio/health-check")
        self.assertEqual(len(self.exporter.get_finished_spans()), 1)


@unittest.skipIf(TestClient is None, "fastapi / opentelemetry sdk unavailable")
class TestUnhandledErrorSpans(unittest.TestCase):
    """RequestContextMiddleware answers a 500 itself, so OTel's own exception handler -- which
    wraps outside it -- never sees the error. Without recording it, Tempo shows a stackless span."""

    SECRET_URL = "https://eodhd.invalid/api/eod/X?api_token=SUPERSECRET_EODHD"

    def setUp(self):
        from backend.app.core.middleware import RequestContextMiddleware
        self.exporter = InMemorySpanExporter()
        app = FastAPI()

        @app.get("/api/boom")
        def boom():
            raise RuntimeError(f"fetch failed for {self.SECRET_URL}")

        app.add_middleware(RequestContextMiddleware)
        self.provider = otel_traces.instrument_app(app, _settings(), exporter=self.exporter)
        self.client = TestClient(app)

    def tearDown(self):
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().uninstrument()
        self.provider.shutdown()
        otel_traces._provider = None

    def test_the_exception_is_recorded_on_the_span_with_secrets_masked(self):
        with self.assertLogs("app.access", "ERROR"):
            res = self.client.get("/api/boom")
        self.assertEqual(res.status_code, 500)
        self.assertEqual(set(res.json()), {"detail", "request_id"})

        span = self.exporter.get_finished_spans()[0]
        self.assertEqual(span.status.status_code.name, "ERROR")
        event = next(e for e in span.events if e.name == "exception")
        self.assertIn("api_token=[redacted]", event.attributes["exception.message"])
        self.assertNotIn("SUPERSECRET_EODHD", event.attributes["exception.stacktrace"])


if __name__ == "__main__":
    unittest.main()
