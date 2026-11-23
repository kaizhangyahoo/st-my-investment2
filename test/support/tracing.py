"""Shared fixture for the manual-span tests.

A traced FastAPI app exporting spans in memory, a transport stub that answers the provider hosts
without a socket, and the attribute-safety guard every piece of the instrumentation has to pass.

Lives here rather than in one test module because three suites now need it, and because the
safety guard is the thing that has to be applied uniformly: a span attribute is a different
retention domain from a log line, so a filename, an account key or a provider URL may be logged
and must never be recorded on a span.
"""
import json
import unittest
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse

try:
    import requests
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import StatusCode
except ImportError:  # pragma: no cover
    TestClient = None

from backend.app.core import otel_traces

TRACING_AVAILABLE = TestClient is not None

# Matches `diagnostics._MAX_LISTED`; duplicated so a test asserting the bound does not read it
# from the module it is bounding.
MAX_LISTED = 20
_MAX_ATTRIBUTE_CHARS = 512


def settings():
    return SimpleNamespace(
        OTEL_EXPORTER_OTLP_ENDPOINT=None,
        OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf",
        OTEL_EXPORTER_OTLP_HEADERS=None,
        OTEL_RESOURCE_ATTRIBUTES="service.namespace=test",
        OTEL_SERVICE_NAME="test-svc",
        ENVIRONMENT="test",
    )


def json_response(request, payload, status=200):
    response = requests.Response()
    response.status_code = status
    response.url = request.url
    response.request = request
    response._content = json.dumps(payload).encode()
    return response


class StubTransport:
    """Answers the provider hosts without a socket, so `RequestsInstrumentor` still produces a
    real client span per call -- which is the thing these tests are about."""

    def __init__(self, yahoo_status=200):
        self.yahoo_status = yahoo_status

    def send(self, request, **kwargs):
        if "query1.finance.yahoo.com" in request.url:
            if self.yahoo_status != 200:
                return json_response(request, {"finance": None}, self.yahoo_status)
            meta = {"regularMarketPrice": 101.5, "currency": "USD"}
            return json_response(request, {"chart": {"result": [{"meta": meta}]}})
        if "api.twelvedata.com" in request.url:
            symbols = parse_qs(urlparse(request.url).query).get("symbol", [""])[0].split(",")
            quotes = {s: {"close": "42.5"} for s in symbols}
            # The real API returns a bare quote for a single symbol and a keyed map for several.
            return json_response(request, quotes if len(symbols) > 1 else quotes[symbols[0]])
        raise AssertionError(f"unexpected outbound host: {request.url}")


def patch_transport(stub):
    return mock.patch.object(requests.adapters.HTTPAdapter, "send", stub.send)


class TracedApp(unittest.TestCase):
    """A traced app whose one route runs the code under test, exporting spans in memory."""

    def _build(self, handler, path="/api/prices"):
        app = FastAPI()
        app.get(path)(handler)
        self.path = path
        self._instrument(app)

    def _build_router(self, router, path, prefix=""):
        """Drive a real router instead of a bespoke handler, for the tests that have to cover
        what a route does either side of the service call."""
        app = FastAPI()
        app.include_router(router, prefix=prefix)
        self.path = f"{prefix}{path}"
        self._instrument(app)
        return app

    def _instrument(self, app):
        from backend.app.core.middleware import RequestContextMiddleware
        self.exporter = InMemorySpanExporter()
        app.add_middleware(RequestContextMiddleware)
        self.provider = otel_traces.instrument_app(app, settings(), exporter=self.exporter)
        self.client = TestClient(app)

    def tearDown(self):
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().uninstrument()
        self.provider.shutdown()
        otel_traces._provider = None

    def spans(self):
        return self.exporter.get_finished_spans()

    def names(self):
        return [s.name for s in self.spans()]

    def server_span(self, method="GET"):
        return next(s for s in self.spans() if s.name == f"{method} {self.path}")

    def named(self, name):
        return next(s for s in self.spans() if s.name == name)

    def all_named(self, name):
        return [s for s in self.spans() if s.name == name]


def assert_attributes_are_safe(case, spans, forbidden=()):
    """Every span attribute is a representable, bounded, non-sensitive value.

    This is the executable form of the rule the instrumentation is built around: carry counts
    and booleans, never the thing itself. `forbidden` holds the values that legitimately exist
    in the test's own fixtures -- the tmpdir path, the CSV basename, the account key, a fake API
    key -- so a careless `str(e)` or `str(path)` reaching an attribute fails here by name.
    """
    for span in spans:
        for key, value in (span.attributes or {}).items():
            where = f"{span.name}.{key}"
            if isinstance(value, tuple):
                case.assertLessEqual(len(value), MAX_LISTED, f"{where} is an unbounded list")
                for item in value:
                    case.assertIsInstance(item, str, f"{where} holds a non-str element")
                strings = list(value)
            else:
                case.assertIsInstance(
                    value, (str, bool, int, float), f"{where} is not a representable type"
                )
                strings = [value] if isinstance(value, str) else []
            for text in strings:
                case.assertLessEqual(
                    len(text), _MAX_ATTRIBUTE_CHARS, f"{where} is an unbounded string"
                )
                for secret in forbidden:
                    case.assertNotIn(secret, text, f"{where} leaked {secret!r}")


def assert_status_not_error(case, spans):
    """Degradation is a successful response carrying a caveat. Marking it an error would make
    the error rate in Grafana count data-quality problems as outages."""
    for span in spans:
        case.assertIsNot(
            span.status.status_code, StatusCode.ERROR, f"{span.name} was marked an error"
        )
