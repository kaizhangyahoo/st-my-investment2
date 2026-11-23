"""Manual spans the auto-instrumentation cannot produce: the provider fan-out must be children
of the request rather than orphan roots, log lines from its worker threads must stay correlated,
and a response served from cache must say so on the span."""
import logging
import unittest
from unittest import mock

try:
    from opentelemetry.trace import SpanKind
except ImportError:  # pragma: no cover
    SpanKind = None

from backend.app.core import otel_traces
from backend.app.core.request_context import RequestContextFilter
from backend.app.core.tracing import annotate, span
from backend.app.services import market_service, price_service
from test.support.tracing import TRACING_AVAILABLE
from test.support.tracing import StubTransport as _StubTransport
from test.support.tracing import TracedApp as _TracedApp
from test.support.tracing import patch_transport as _patch_transport

TICKERS = ["AAA", "BBB", "CCC"]


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestProviderFanOutSpans(_TracedApp):
    def setUp(self):
        def prices():
            fetched, failures = price_service.get_prices(TICKERS)
            return {"prices": fetched, "failures": failures}

        self._build(prices)

    def test_the_yahoo_fan_out_is_parented_on_the_request_not_orphaned(self):
        stub = _StubTransport()
        with _patch_transport(stub):
            self.assertEqual(self.client.get(self.path).status_code, 200)

        tier, server = self.named("price.yahoo"), self.server_span()
        # By kind, not by name or by having a url: the server span carries `http.url` too.
        fetches = [s for s in self.spans() if s.kind is SpanKind.CLIENT]
        self.assertEqual(len(fetches), len(TICKERS))
        for fetch in fetches:
            # The whole point: context crosses the thread boundary, so these are not own-roots.
            self.assertEqual(fetch.context.trace_id, server.context.trace_id)
            self.assertEqual(fetch.parent.span_id, tier.context.span_id)
        self.assertEqual(tier.parent.span_id, server.context.span_id)
        self.assertEqual(tier.attributes["price.requested"], 3)
        self.assertEqual(tier.attributes["price.priced"], 3)

    def test_a_log_line_from_a_worker_thread_carries_the_requests_own_ids(self):
        seen = []

        def capture(ticker):
            record = logging.LogRecord("t", logging.INFO, "", 0, "m", None, None)
            RequestContextFilter().filter(record)
            seen.append((record.request_id, record.trace_id))
            return 10.0

        with mock.patch.object(price_service, "fetch_yahoo_price", capture):
            self.assertEqual(self.client.get(self.path).status_code, 200)

        self.assertEqual(len(seen), len(TICKERS))
        request_ids = {request_id for request_id, _ in seen}
        self.assertEqual(len(request_ids), 1, "workers disagreed on the request id")
        self.assertTrue(request_ids.pop(), "worker log lines carried no request id")
        expected = format(self.server_span().context.trace_id, "032x")
        self.assertEqual({trace for _, trace in seen}, {expected})

    def test_a_fallback_tier_records_how_many_tickers_it_rescued(self):
        stub = _StubTransport(yahoo_status=500)
        with mock.patch.object(price_service, "_twelvedata_keys", lambda: ["dummy"]), \
                _patch_transport(stub):
            self.assertEqual(self.client.get(self.path).status_code, 200)

        self.assertEqual(self.named("price.yahoo").attributes["price.priced"], 0)
        twelvedata = self.named("price.twelvedata")
        self.assertEqual(twelvedata.attributes["price.requested"], 3)
        self.assertEqual(twelvedata.attributes["price.priced"], 3)
        # No dotted tickers, so the EODHD tier never ran and must not appear in the trace.
        self.assertNotIn("price.eodhd", {s.name for s in self.spans()})


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestPriceCacheAttributes(_TracedApp):
    def setUp(self):
        market_service.cache.clear()
        self._build(lambda: {"prices": market_service.get_current_prices(TICKERS)[0]},
                    path="/api/current")

    def tearDown(self):
        market_service.cache.clear()
        super().tearDown()

    def test_a_miss_names_the_cache_and_counts_what_it_had_to_fetch(self):
        with _patch_transport(_StubTransport()):
            self.assertEqual(self.client.get(self.path).status_code, 200)

        server = self.server_span()
        self.assertIs(server.attributes["cache.current_price.hit"], False)
        self.assertEqual(server.attributes["cache.current_price.hits"], 0)
        self.assertEqual(server.attributes["cache.current_price.misses"], 3)
        # The cache is named by the key, so a second cache on the same span cannot overwrite it.
        self.assertNotIn("cache.name", server.attributes)
        self.assertNotIn("cache.hit", server.attributes)

    def test_a_fully_cached_response_is_distinguishable_from_one_that_hit_a_provider(self):
        with _patch_transport(_StubTransport()):
            self.assertEqual(self.client.get(self.path).status_code, 200)
            self.exporter.clear()
            self.assertEqual(self.client.get(self.path).status_code, 200)

        server = self.server_span()
        self.assertIs(server.attributes["cache.current_price.hit"], True)
        self.assertEqual(server.attributes["cache.current_price.hits"], 3)
        self.assertEqual(server.attributes["cache.current_price.misses"], 0)
        # Nothing reached a provider, so the request span is the only span in the trace.
        self.assertEqual(len(self.spans()), 1)


class TestHelpersWhileTracingIsOff(unittest.TestCase):
    """The suite runs with no endpoint, so this is the state every other test exercises the
    services in -- annotating must stay free and must not need OpenTelemetry at all."""

    def setUp(self):
        self.saved, otel_traces._provider = otel_traces._provider, None

    def tearDown(self):
        otel_traces._provider = self.saved

    def test_span_and_annotate_are_inert_without_a_provider(self):
        with span("price.yahoo", **{"price.requested": 1}) as active:
            active.set_attribute("price.priced", 1)
        annotate(**{"cache.current_price.hit": True})


if __name__ == "__main__":
    unittest.main()
