"""Cache hit/miss counters, accumulated on whichever `tracing.span` is open.

A cache hit is the absence of work: it opens no span of its own and makes no HTTP call for
`RequestsInstrumentor` to see, so a fully-cached response and one that fetched thirty prices are
indistinguishable in a trace. These counters are that difference.

They are flushed onto the enclosing span, which makes the pairing load-bearing in both
directions: a counter recorded with no span open is dropped silently *by design* (the
alternative is a process-global tally, which is the per-request trap this avoids), so every
instrumented cache has to sit inside a guaranteed span. The tests that pin that pairing are the
T212 and statement ones -- nothing else catches a span being trimmed away later.
"""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock
from unittest.mock import patch

import pandas as pd

from backend.app.core import otel_traces
from backend.app.core.cache import cache, ttl_cache
from backend.app.core.tracing import (
    _CACHE_COUNTS,
    record_cache_hit,
    record_cache_miss,
    span,
)
from backend.app.services import history_service, market_service, t212_service
from test.support.t212 import FakeT212Client, filled_order, page
from test.support.tracing import (
    TRACING_AVAILABLE,
    StubTransport,
    TracedApp,
    assert_attributes_are_safe,
    patch_transport,
)

TICKERS = ["AAA", "BBB", "CCC"]
DATES = ["2024-01-02", "2024-01-03", "2024-01-04"]
START = "2024-01-01"

STATEMENT_NAME = "TradeHistory-QX2B3-(04-01-2024).csv"
STATEMENT_CSV = "Market,Quantity,TextDate\nApple Inc,10,02-01-2024\n"

_CALLS = []


@ttl_cache(ttl=3600, name="demo")
def _demo(key: str) -> str:
    _CALLS.append(key)
    return key.upper()


@ttl_cache(ttl=3600, name="other")
def _other(key: str) -> str:
    return key


def _frame() -> pd.DataFrame:
    df = pd.DataFrame({"Date": pd.to_datetime(DATES), "close": [100.0, 110.0, 120.0]})
    df.attrs["currency"] = "USD"
    return df


class _CacheCase(TracedApp):
    """Every case shares the one `TTLCache` singleton, so it has to be emptied either side."""

    def _isolate_cache(self):
        cache.clear()
        _CALLS.clear()
        self.addCleanup(_CALLS.clear)
        self.addCleanup(cache.clear)


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestAccumulation(_CacheCase):
    """The failure mode the first slice deferred: a flat `cache.hit` set once per lookup reports
    only the last ticker of a loop. These land once, on the span that contains the loop."""

    def setUp(self):
        self._isolate_cache()
        self._build(self._handler, path="/api/counted")

    def _handler(self):
        with span("loop"):
            _demo("a")
            _demo("a")
            _demo("b")
        return {"calls": len(_CALLS)}

    def test_a_loop_of_lookups_lands_one_key_set_on_the_span_that_contains_it(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)

        loops = self.all_named("loop")
        self.assertEqual(len(loops), 1)
        attributes = loops[0].attributes
        self.assertEqual(attributes["cache.demo.hits"], 1)
        self.assertEqual(attributes["cache.demo.misses"], 2)
        self.assertIs(attributes["cache.demo.hit"], False)
        # Two distinct arguments, so the function really did run twice.
        self.assertEqual(_CALLS, ["a", "b"])


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestTwoCachesOnOneSpan(_CacheCase):
    """The collision the namespacing exists to prevent. With flat keys the second cache to flush
    would overwrite the first and the span would describe only one of them."""

    def setUp(self):
        self._isolate_cache()
        self._build(self._handler, path="/api/two")

    def _handler(self):
        with span("loop"):
            _demo("a")
            _demo("a")
            _other("a")
        return {"ok": True}

    def test_neither_cache_overwrites_the_other(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        attributes = self.named("loop").attributes

        # Asserted as a total first, because that is what an overwrite destroys: three lookups
        # were made, and a flat key set would report whichever cache flushed last.
        counted = sum(
            value for key, value in attributes.items()
            if key.endswith(".hits") or key.endswith(".misses")
        )
        self.assertEqual(counted, 3, "a cache flushed over another cache's counts")
        self.assertEqual(
            {key for key in attributes if key.endswith(".hit")},
            {"cache.demo.hit", "cache.other.hit"},
        )

        self.assertEqual(attributes["cache.demo.hits"], 1)
        self.assertEqual(attributes["cache.demo.misses"], 1)
        self.assertEqual(attributes["cache.other.hits"], 0)
        self.assertEqual(attributes["cache.other.misses"], 1)
        self.assertIs(attributes["cache.other.hit"], False)


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestNesting(_CacheCase):
    def setUp(self):
        self._isolate_cache()
        self._build(self._handler, path="/api/nested")

    def _handler(self):
        _demo("a")  # Primes the key, with no span open, so the hit below is a real hit.
        with span("parent"):
            _demo("a")
            with span("child"):
                _demo("b")
        return {"ok": True}

    def test_a_parent_reports_its_whole_subtree_and_a_child_only_its_own(self):
        """Inclusive, so `cache.*` on a span means what its duration means. Exclusive would leave
        `history.compute` carrying nothing at all, since every lookup happens in a child."""
        self.assertEqual(self.client.get(self.path).status_code, 200)

        parent = self.named("parent").attributes
        self.assertEqual(parent["cache.demo.hits"], 1)
        self.assertEqual(parent["cache.demo.misses"], 1)
        # One of the two lookups missed, so the subtree did reach the function.
        self.assertIs(parent["cache.demo.hit"], False)

        child = self.named("child").attributes
        self.assertEqual(child["cache.demo.hits"], 0)
        self.assertEqual(child["cache.demo.misses"], 1)


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestNoEnclosingSpan(_CacheCase):
    def setUp(self):
        self._isolate_cache()
        self._build(self._handler, path="/api/orphan")

    def _handler(self):
        # The server span is `FastAPIInstrumentor`'s, not one of ours, so nothing is counting.
        record_cache_hit("orphan")
        record_cache_miss("orphan")
        return {"ok": True}

    def test_a_lookup_with_no_span_open_is_dropped_without_raising(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)

        attributes = self.server_span().attributes
        self.assertNotIn("cache.orphan.hits", attributes)
        self.assertNotIn("cache.orphan.misses", attributes)


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestPriceHistoryCounters(_CacheCase):
    """The real `_price_frame` loop over the real `ttl_cache`, with only the provider call stubbed
    -- patching `get_price_history` instead would bypass the cache being measured."""

    def setUp(self):
        self._isolate_cache()
        self.fetches = []
        patcher = patch.object(market_service, "fetch_yahoo_history", self._fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._build(self._handler, path="/api/history")

    def _fetch(self, ticker, start_date):
        self.fetches.append(ticker)
        return _frame()

    def _handler(self):
        closes, _currencies, unpriced = history_service._price_frame(TICKERS, START)
        return {"priced": len(closes), "unpriced": unpriced}

    def test_a_cold_frame_misses_every_ticker_and_a_warm_one_hits_every_ticker(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        cold = self.named("history.price_frame").attributes
        self.assertEqual(cold["cache.price_history.misses"], len(TICKERS))
        self.assertEqual(cold["cache.price_history.hits"], 0)
        self.assertIs(cold["cache.price_history.hit"], False)

        self.exporter.clear()
        self.assertEqual(self.client.get(self.path).status_code, 200)
        warm = self.named("history.price_frame").attributes
        self.assertEqual(warm["cache.price_history.hits"], len(TICKERS))
        self.assertEqual(warm["cache.price_history.misses"], 0)
        self.assertIs(warm["cache.price_history.hit"], True)
        # The counters agree with the thing they claim to measure: the provider was not re-asked.
        self.assertEqual(self.fetches, TICKERS)
        assert_attributes_are_safe(self, self.spans())


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestOhlcCounters(_CacheCase):
    """`get_ohlc` had no span, so `cache.ohlc.*` would have been dropped. `market.ohlc` exists for
    the counter, which is why its absence has to fail a test rather than go unnoticed."""

    def setUp(self):
        self._isolate_cache()
        self.failing = False
        patcher = patch.object(market_service, "fetch_yahoo_history", self._fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._build(self._handler, path="/api/ohlc")

    def _fetch(self, ticker, start_date):
        if self.failing:
            raise ValueError("provider is down")
        return _frame()

    def _handler(self):
        rows = [len(market_service.get_ohlc("AAA", START)) for _ in range(2)]
        return {"rows": rows}

    def test_the_chart_cache_reports_a_miss_then_a_hit(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)

        first, second = self.all_named("market.ohlc")
        self.assertEqual(first.attributes["cache.ohlc.misses"], 1)
        self.assertIs(first.attributes["cache.ohlc.hit"], False)
        self.assertEqual(second.attributes["cache.ohlc.hits"], 1)
        self.assertIs(second.attributes["cache.ohlc.hit"], True)

    def test_a_refused_result_reads_as_uncacheable_rather_than_as_a_cold_cache(self):
        """A provider failing every call never fills the key, so every request misses. Without
        this counter that is indistinguishable from a cache nobody has warmed yet (KAN-53)."""
        self.failing = True
        self.assertEqual(self.client.get(self.path).status_code, 200)

        for attempt in self.all_named("market.ohlc"):
            self.assertEqual(attempt.attributes["cache.ohlc.misses"], 1)
            self.assertEqual(attempt.attributes["cache.ohlc.uncacheable"], 1)
            self.assertIs(attempt.attributes["cache.ohlc.hit"], False)


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestCoexistence(_CacheCase):
    """`current_price` is counted by hand on the request span and `price_history` by the
    accumulator on a child. Both have to survive in one trace, which is what the namespacing
    buys -- with flat keys the second writer would silently win."""

    def setUp(self):
        self._isolate_cache()
        patcher = patch.object(market_service, "fetch_yahoo_history", lambda *a: _frame())
        patcher.start()
        self.addCleanup(patcher.stop)
        self._build(self._handler, path="/api/both")

    def _handler(self):
        prices, _failures = market_service.get_current_prices(TICKERS)
        history_service._price_frame(TICKERS, START)
        return {"prices": prices}

    def test_the_hand_written_and_the_accumulated_counters_both_survive(self):
        with patch_transport(StubTransport()):
            self.assertEqual(self.client.get(self.path).status_code, 200)

        server = self.server_span().attributes
        self.assertEqual(server["cache.current_price.misses"], len(TICKERS))
        self.assertIs(server["cache.current_price.hit"], False)
        # The accumulated set is on the child and did not land on, or displace, the request span.
        self.assertNotIn("cache.price_history.misses", server)
        frame = self.named("history.price_frame").attributes
        self.assertEqual(frame["cache.price_history.misses"], len(TICKERS))
        assert_attributes_are_safe(self, self.spans())


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestT212InstrumentCounters(_CacheCase):
    """The symbol map is 18.5k instruments behind a 6-requests-per-minute budget, so whether a
    request paid for it is the question. `t212.instruments` wraps the cache check inside the
    function precisely so all three callers are covered."""

    def setUp(self):
        self._isolate_cache()
        self.client212 = FakeT212Client(order_pages=[page([filled_order(order_id="1")])])
        patcher = patch.object(
            t212_service, "get_t212_client", lambda *a, **kw: self.client212
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self._build(lambda: t212_service.fetch_t212_orders(max_pages=1), path="/api/t212")

    def test_the_second_request_hits_the_map_and_asks_the_platform_nothing(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.assertEqual(
            self.named("t212.instruments").attributes["cache.t212_instruments.misses"], 1
        )

        self.exporter.clear()
        self.assertEqual(self.client.get(self.path).status_code, 200)
        attributes = self.named("t212.instruments").attributes
        self.assertEqual(attributes["cache.t212_instruments.hits"], 1)
        self.assertIs(attributes["cache.t212_instruments.hit"], True)
        # The counter and the call log have to agree, or the counter is measuring nothing.
        self.assertEqual(self.client212.calls.count("instruments"), 1)


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestStatementCounters(_CacheCase):
    """`trades.load_statement` wraps the in-memory check rather than just the load, so the hit
    has a span to land on. A span that covered only the miss branch would leave every hit
    unreported, which is the same blind spot the counters exist to close."""

    def setUp(self):
        from backend.app.api.v1 import trades

        self._isolate_cache()
        self.trades = trades
        self.tmpdir = tempfile.mkdtemp(prefix="verify_cache_counters_")
        self.downloads = os.path.join(self.tmpdir, "Downloads")
        os.makedirs(self.downloads)
        with open(os.path.join(self.downloads, STATEMENT_NAME), "w") as f:
            f.write(STATEMENT_CSV)

        for store in (trades._LAST_TRADE_DF, trades._LAST_TRANSACTION_DF,
                      trades._LAST_TRADE_FILENAME, trades._LAST_TRANSACTION_FILENAME,
                      trades._USER_MANUAL_UPLOAD):
            store.clear()
            self.addCleanup(store.clear)

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch(
            "os.path.expanduser",
            lambda p: self.downloads if p == "~/Downloads" else p,
        ))
        self._build(self._handler, path="/api/statement")

    def _handler(self):
        df, _filename = self.trades.get_or_load_trade_df("default")
        return {"rows": 0 if df is None else len(df)}

    def test_the_first_request_parses_the_csv_and_the_second_does_not(self):
        self.assertEqual(self.client.get(self.path).json(), {"rows": 1})
        cold = self.named("trades.load_statement").attributes
        self.assertEqual(cold["cache.trade_df.misses"], 1)
        self.assertIs(cold["cache.trade_df.hit"], False)
        # Paired with the parse it paid for, so the miss is attributable to real work.
        self.assertEqual(cold["statement.rows"], 1)

        self.exporter.clear()
        self.assertEqual(self.client.get(self.path).json(), {"rows": 1})
        warm = self.named("trades.load_statement").attributes
        self.assertEqual(warm["cache.trade_df.hits"], 1)
        self.assertIs(warm["cache.trade_df.hit"], True)
        self.assertNotIn("statement.rows", warm)
        # The scan is the expensive half of a miss, and a hit must not reach it at all.
        self.assertNotIn("trades.scan_downloads", self.names())

    def test_no_counter_carries_a_path_a_filename_or_an_account_id(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        assert_attributes_are_safe(
            self, self.spans(), forbidden=(self.tmpdir, STATEMENT_NAME, "QX2B3")
        )


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestTickerMapCounters(_CacheCase):
    """The ticker map is read during portfolio resolution. `portfolio.resolve_tickers`
    is the enclosing span that carries `cache.ticker_map.*` (KAN-68)."""

    def setUp(self):
        from backend.app.core.config import settings
        from backend.app.services.ticker_service import load_ticker_mappings

        self._isolate_cache()
        load_ticker_mappings.clear()
        self.addCleanup(load_ticker_mappings.clear)

        self.tmpdir = tempfile.mkdtemp(prefix="verify_ticker_map_counters_")
        self.map_file = os.path.join(self.tmpdir, "company_name_to_ticker.json")
        with open(self.map_file, "w") as f:
            json.dump({"Apple Inc": "AAPL"}, f)

        patcher = patch.object(settings, "TICKER_MAP_FILE", self.map_file)
        patcher.start()
        self.addCleanup(patcher.stop)

        self._build(self._handler, path="/api/ticker_map")

    def _handler(self):
        from test.support.portfolio import run_engine, trade_df

        return run_engine(trade_df())

    def test_cold_and_warm_resolution_spans_report_ticker_map_counts(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        cold = self.named("portfolio.resolve_tickers").attributes
        # Cold: first load is a miss, second load inside find_unresolved_symbols is a hit
        self.assertEqual(cold["cache.ticker_map.misses"], 1)
        self.assertEqual(cold["cache.ticker_map.hits"], 1)
        self.assertIs(cold["cache.ticker_map.hit"], False)

        self.exporter.clear()
        self.assertEqual(self.client.get(self.path).status_code, 200)
        warm = self.named("portfolio.resolve_tickers").attributes
        self.assertEqual(warm["cache.ticker_map.misses"], 0)
        self.assertEqual(warm["cache.ticker_map.hits"], 2)
        self.assertIs(warm["cache.ticker_map.hit"], True)

        assert_attributes_are_safe(self, self.spans())


class TestCountersWhileTracingIsOff(unittest.TestCase):
    """The state every other suite in this repo runs in. The ContextVar is never set, so a
    recorded lookup costs one `ContextVar.get()` and nothing else."""

    def setUp(self):
        self.saved, otel_traces._provider = otel_traces._provider, None
        cache.clear()
        _CALLS.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(_CALLS.clear)

    def tearDown(self):
        otel_traces._provider = self.saved

    def test_nothing_is_counted_and_nothing_raises(self):
        record_cache_hit("demo")
        with span("loop") as active:
            self.assertIsNone(_CACHE_COUNTS.get())
            _demo("a")
            active.set_attribute("ok", True)
        self.assertIsNone(_CACHE_COUNTS.get())
        self.assertEqual(_CALLS, ["a"])


if __name__ == "__main__":
    unittest.main()
