"""AC 3: one trace for the compute route has to attribute time to CSV load, the providers and
the pandas valuation separately.

`FastAPIInstrumentor` gives one server span and `RequestsInstrumentor` one span per HTTP call, so
between them nothing can say which third of the request the time went to -- the valuation does no
I/O at all and is therefore invisible to both. These tests drive the real router rather than a
bespoke handler, because the CSV load happens in the route *before* `compute_history` is entered,
so a test that called the service directly could not cover the third the AC names first.

Every provider is patched on the `history_service` / `portfolio_engine` bindings, which sidesteps
the module-level `ttl_cache` singleton and keeps the suite offline.
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
from backend.app.core.config import settings
from backend.app.services import history_service, realised_pnl, t212_service
from backend.app.services.benchmark_service import deposit_matched_series
from backend.app.services.risk_metrics import TIMEFRAMES
from test.support.portfolio import TRADE_CSV, temp_fx_store, trade_df, run_engine
from test.support.t212 import FakeT212Client, filled_order, page
from test.support.tracing import TRACING_AVAILABLE, TracedApp, assert_attributes_are_safe

MAPPINGS = {"Apple Inc": "AAPL", "Vodafone Group": "VOD.L"}
DATES = ["2024-01-02", "2024-01-03", "2024-01-04"]
GBPUSD, GBPEUR = 2.0, 1.25

# Named like a real IG export, so the account id in the basename is present for the safety guard
# to prove never reaches an attribute.
STATEMENT_NAME = "TradeHistory-QX2B3-(04-01-2024).csv"
STATEMENT_CSV = (
    "Market,Quantity,TextDate\n"
    "Apple Inc,10,02-01-2024\n"
    "Vodafone Group,100,02-01-2024\n"
)
ACCOUNT_KEY = "ig:default"


def _closes(values):
    return pd.DataFrame({"Date": pd.to_datetime(DATES), "close": values})


def _fx(_start):
    index = pd.to_datetime(DATES)
    return (
        {
            "GBPUSD=X": pd.Series([GBPUSD] * len(index), index=index),
            "GBPEUR=X": pd.Series([GBPEUR] * len(index), index=index),
        },
        False,
    )


PRICES = {"AAPL": (_closes([100.0, 110.0, 120.0]), "USD"),
          "VOD.L": (_closes([70.0, 72.0, 74.0]), "GBp")}


def _temp_mapping(case, mappings):
    """A throwaway ticker map, so resolution runs for real without touching the repo's own."""
    path = os.path.join(tempfile.mkdtemp(prefix="verify_spans_map_"), "ticker_map.json")
    with open(path, "w") as f:
        json.dump(mappings, f)
    from backend.app.services.ticker_service import load_ticker_mappings
    load_ticker_mappings.clear()
    case.addCleanup(load_ticker_mappings.clear)
    patcher = patch.object(settings, "TICKER_MAP_FILE", path)
    patcher.start()
    case.addCleanup(patcher.stop)
    case.assertEqual(settings.TICKER_MAP_FILE, path)


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestComputeRouteTrace(TracedApp):
    """`POST /portfolio/history/compute` end to end, with the statement on disk.

    `~/Downloads` is redirected rather than `find_latest_download_files` patched out, so the scan
    and `pd.read_csv` both run and the load really is the span being measured.
    """

    def setUp(self):
        from backend.app.api.v1 import portfolio, trades

        temp_fx_store(self)
        _temp_mapping(self, MAPPINGS)
        self.tmpdir = tempfile.mkdtemp(prefix="verify_compute_spans_")
        self.downloads = os.path.join(self.tmpdir, "Downloads")
        os.makedirs(self.downloads)
        self.statement = os.path.join(self.downloads, STATEMENT_NAME)
        with open(self.statement, "w") as f:
            f.write(STATEMENT_CSV)
        self.values_path = os.path.join(self.tmpdir, "user_portfolio_values.json")

        for store in (trades._LAST_TRADE_DF, trades._LAST_TRANSACTION_DF,
                      trades._LAST_TRADE_FILENAME, trades._LAST_TRANSACTION_FILENAME,
                      trades._USER_MANUAL_UPLOAD):
            store.clear()
            self.addCleanup(store.clear)

        self.price_calls = []
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(settings, "PORTFOLIO_VALUES_FILE", self.values_path))
        stack.enter_context(mock.patch(
            "os.path.expanduser",
            lambda p: self.downloads if p == "~/Downloads" else p,
        ))
        stack.enter_context(patch.object(
            history_service, "get_price_history", self._price_history
        ))
        stack.enter_context(patch.object(history_service, "get_historical_fx", _fx))

        self._build_router(portfolio.router, "/portfolio/history/compute", prefix="/api/v1")

    def _price_history(self, ticker, start_date):
        self.price_calls.append(ticker)
        return PRICES.get(ticker, (pd.DataFrame(columns=["Date", "close"]), None))

    def _compute(self):
        response = self.client.post(self.path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_the_trace_attributes_csv_load_providers_and_valuation_separately(self):
        body = self._compute()
        self.assertEqual(len(body["points"]), len(DATES))

        server = self.server_span(method="POST")
        names = set(self.names())
        # One name per third of the AC, and the valuation third is the one neither instrumentor
        # could ever have produced: it opens no socket.
        for third in ("trades.load_statement", "history.price_history", "history.value_series"):
            self.assertIn(third, names)
        for recorded in self.spans():
            self.assertEqual(
                recorded.context.trace_id, server.context.trace_id,
                f"{recorded.name} is in a different trace from the request",
            )

        load = self.named("trades.load_statement")
        self.assertEqual(load.attributes["statement.kind"], "trade")
        self.assertEqual(load.attributes["statement.rows"], 2)
        self.assertEqual(self.named("history.value_series").attributes["value.days"], len(DATES))
        self.assertEqual(self.named("history.value_series").attributes["value.invalid_days"], 0)

    def test_the_scan_and_the_compute_report_what_they_found(self):
        self._compute()

        scan = self.named("trades.scan_downloads")
        self.assertEqual(scan.attributes["scan.candidates"], 1)
        self.assertIs(scan.attributes["scan.found_trade"], True)
        self.assertIs(scan.attributes["scan.found_transaction"], False)

        compute = self.named("history.compute")
        self.assertIs(compute.attributes["history.force_recompute"], False)
        self.assertEqual(compute.attributes["trades.rows"], 2)
        self.assertEqual(compute.attributes["history.tickers"], 2)
        self.assertEqual(compute.attributes["history.unpriced"], 0)
        # Cache vocabulary because that is what the `pending` filter is: a hit/miss over the
        # shared portfolio-values file.
        self.assertEqual(compute.attributes["cache.history_days.hits"], 0)
        self.assertEqual(compute.attributes["cache.history_days.misses"], len(DATES))
        self.assertIs(compute.attributes["cache.history_days.hit"], False)

    def test_a_second_compute_reports_every_date_as_already_stored(self):
        self._compute()
        self.exporter.clear()
        self._compute()

        compute = self.named("history.compute")
        self.assertEqual(compute.attributes["cache.history_days.hits"], len(DATES))
        self.assertEqual(compute.attributes["cache.history_days.misses"], 0)
        self.assertIs(compute.attributes["cache.history_days.hit"], True)
        # Nothing was valued, so the valuation spans are absent rather than present and empty.
        self.assertNotIn("history.value_series", self.names())
        self.assertNotIn("history.cache_write", self.names())

    def test_every_child_parents_on_the_span_whose_work_contains_it(self):
        self._compute()

        compute = self.named("history.compute")
        frame = self.named("history.price_frame")
        self.assertEqual(frame.parent.span_id, compute.context.span_id)
        for name in ("history.fx_frames", "history.to_gbp", "history.holdings",
                     "history.value_series", "history.cache_write"):
            self.assertEqual(
                self.named(name).parent.span_id, compute.context.span_id,
                f"{name} is not parented on history.compute",
            )

        fetches = self.all_named("history.price_history")
        self.assertEqual(len(fetches), 2, "one span per ticker, as the sequential loop warrants")
        self.assertEqual(
            {f.attributes["price.ticker"] for f in fetches}, {"AAPL", "VOD.L"}
        )
        for fetch in fetches:
            self.assertEqual(fetch.parent.span_id, frame.context.span_id)
            self.assertEqual(fetch.attributes["price.rows"], len(DATES))
        self.assertEqual(frame.attributes["price.tickers"], 2)
        self.assertEqual(frame.attributes["price.unpriced"], 0)

    def test_the_shared_values_file_is_read_twice_in_one_computing_request(self):
        """Was four (KAN-69): the pending-date filter, the merge, the response's points and the
        route's account list each opened the file. Three of those now share the request's copy.

        Two and not one, for a reason worth pinning rather than tolerating: `_merge_and_write`
        goes back to disk on purpose. Its copy would otherwise date from before the price
        fetches, and a legacy Streamlit write landing in that window would be merged out of
        existence -- the lost update the atomic replace exists to prevent.
        """
        self._compute()
        self.assertEqual(len(self.all_named("history.cache_read")), 2)

    def test_a_request_that_computes_nothing_reads_the_shared_values_file_once(self):
        """With every date already stored there is no merge, so the one remaining read is the
        pending-date filter and the request's copy answers everything after it."""
        self._compute()
        self.exporter.clear()
        self._compute()

        self.assertNotIn("history.cache_write", self.names())
        self.assertEqual(len(self.all_named("history.cache_read")), 1)

    def test_instrumentation_does_not_change_what_the_providers_are_asked_for(self):
        """The quota constraint, asserted directly: EODHD serves ~20 requests a day and one
        TwelveData key forces a 3-minute sleep, so an extra fetch is not a cosmetic regression."""
        traced = self._compute_in_isolation()
        saved, otel_traces._provider = otel_traces._provider, None
        try:
            untraced = self._compute_in_isolation()
        finally:
            otel_traces._provider = saved

        self.assertEqual(traced[0], untraced[0])
        self.assertEqual(traced[1], untraced[1])
        self.assertEqual(traced[0], ["AAPL", "VOD.L"])

    def _compute_in_isolation(self):
        with open(self.values_path, "w") as f:
            json.dump({}, f)
        self.price_calls.clear()
        result = history_service.compute_history(
            pd.read_csv(self.statement), ACCOUNT_KEY
        )
        return list(self.price_calls), result["data_quality"]

    def test_no_attribute_carries_a_path_a_filename_or_an_account_key(self):
        self._compute()
        assert_attributes_are_safe(
            self,
            self.spans(),
            forbidden=(self.tmpdir, STATEMENT_NAME, "QX2B3", ACCOUNT_KEY),
        )


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestPositionsSpans(TracedApp):
    def setUp(self):
        _temp_mapping(self, {"Apple Inc": "AAPL"})
        self._build(lambda: run_engine(trade_df()), path="/api/positions")

    def test_the_positions_tree_separates_resolution_grouping_and_valuation(self):
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()

        positions = self.named("portfolio.positions")
        self.assertEqual(positions.attributes["trades.rows"], 3)
        # "Bogus Ltd" is unmapped and owns 2 of the 3 rows.
        self.assertEqual(positions.attributes["trades.excluded_rows"], 2)
        self.assertEqual(positions.attributes["positions.count"], 1)
        self.assertEqual(positions.attributes["positions.unpriced"], 0)
        self.assertIs(positions.attributes["fx.fallback"], False)

        resolve = self.named("portfolio.resolve_tickers")
        self.assertEqual(resolve.parent.span_id, positions.context.span_id)
        self.assertEqual(
            resolve.attributes["tickers.unresolved"], len(body["unresolved_symbols"])
        )
        for name in ("portfolio.group", "portfolio.fx", "portfolio.value"):
            self.assertEqual(self.named(name).parent.span_id, positions.context.span_id)
        self.assertEqual(self.named("portfolio.value").attributes["positions.count"], 1)
        assert_attributes_are_safe(self, self.spans(), forbidden=("Bogus Ltd",))


REALISED_CSV = (
    "TextDate,Time,Market,Quantity,Cost/Proceeds,Activity\n"
    "02-01-2024,10:00:00,Apple Inc,10,-1000.00,TRADE\n"
    "03-01-2024,10:00:00,Apple Inc,-10,1200.00,TRADE\n"
)


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestRealisedSpans(TracedApp):
    def setUp(self):
        import io

        _temp_mapping(self, {"Apple Inc": "AAPL"})
        self.df = pd.read_csv(io.StringIO(REALISED_CSV))
        self._build(lambda: self._handler(), path="/api/realised")

    def _handler(self):
        book = realised_pnl.compute_disposals(self.df)
        realised_pnl.all_windows(book["disposals"])
        return {"disposals": len(book["disposals"])}

    def test_the_book_and_the_windows_each_report_what_they_walked(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)

        book = self.named("realised.disposals")
        self.assertEqual(book.attributes["trades.rows"], 2)
        self.assertEqual(book.attributes["disposals.count"], 1)
        self.assertEqual(book.attributes["disposals.excluded"], 0)
        self.assertEqual(book.attributes["corporate_action.rows"], 0)

        windows = self.named("realised.windows")
        self.assertEqual(windows.attributes["disposals.included"], 1)
        # One span for every timeframe rather than one each: the pair of counts is what makes the
        # repeated pass over the same disposals visible.
        self.assertEqual(windows.attributes["windows.count"], len(TIMEFRAMES))


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestT212HistorySpans(TracedApp):
    def setUp(self):
        from backend.app.core.cache import cache

        cache.clear()
        self.addCleanup(cache.clear)
        self.client212 = FakeT212Client(order_pages=[
            page([filled_order(order_id="1")], next_cursor=111),
            page([filled_order(order_id="2")], next_cursor=222, cursor=111),
            page([filled_order(order_id="3")], cursor=222),
        ])
        patcher = patch.object(
            t212_service, "get_t212_client", lambda *a, **kw: self.client212
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self._build(lambda: t212_service.fetch_t212_orders(max_pages=2), path="/api/t212")

    def test_the_page_walk_records_that_it_left_data_behind(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)

        orders = self.named("t212.orders_history")
        self.assertEqual(orders.attributes["t212.pages"], 2)
        self.assertEqual(orders.attributes["t212.max_pages"], 2)
        self.assertEqual(orders.attributes["t212.items"], 2)
        # The value nothing recorded before: each page costs one of 6 requests a minute, so the
        # panel shows a window and has to be able to say so.
        self.assertIs(orders.attributes["t212.truncated"], True)

    def test_the_symbol_map_is_built_once_and_named_by_its_own_span(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)

        instruments = self.named("t212.instruments")
        self.assertEqual(instruments.attributes["t212.exchanges"], 4)
        # Bucharest is not a venue Yahoo covers and one instrument has no schedule, so 3 of 5
        # instruments are chartable.
        self.assertEqual(instruments.attributes["t212.instruments"], 3)
        self.assertEqual(self.client212.calls.count("instruments"), 1)


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestBenchmarkAnnotations(TracedApp):
    """Annotated, not spanned: the benchmark does arithmetic over an already-fetched frame, so
    the question it has to answer in Grafana is "why was the line withheld", not "why was it
    slow"."""

    def setUp(self):
        self.args = (None, None, [])
        self._build(lambda: self._handler(), path="/api/benchmark")

    def _handler(self):
        deposit_matched_series(*self.args)
        return {"ok": True}

    def _annotate(self, closes, currency, cashflows):
        self.exporter.clear()
        self.args = (closes, currency, cashflows)
        self.assertEqual(self.client.get(self.path).status_code, 200)
        return self.server_span().attributes

    def test_each_withheld_reason_reaches_the_request_span(self):
        deposit = [{"date": "2024-01-02", "amount_gbp": 1000.0}]
        frame = _closes([100.0, 110.0, 120.0])

        attrs = self._annotate(frame, "USD", deposit)
        self.assertEqual(attrs["benchmark.withheld_reason"], "non_gbp_quote")
        self.assertEqual(attrs["benchmark.closes"], len(DATES))
        self.assertEqual(attrs["benchmark.cashflows"], 1)

        attrs = self._annotate(frame, "GBP", [])
        self.assertEqual(attrs["benchmark.withheld_reason"], "no_cashflows")
        self.assertEqual(attrs["benchmark.cashflows"], 0)

        attrs = self._annotate(pd.DataFrame(columns=["Date", "close"]), "GBP", deposit)
        self.assertEqual(attrs["benchmark.withheld_reason"], "no_closes")
        self.assertEqual(attrs["benchmark.closes"], 0)

    def test_a_built_line_reports_what_it_matched_and_names_no_reason(self):
        attrs = self._annotate(
            _closes([100.0, 110.0, 120.0]), "GBp",
            [{"date": "2024-01-02", "amount_gbp": 1000.0}],
        )
        self.assertNotIn("benchmark.withheld_reason", attrs)
        self.assertEqual(attrs["benchmark.deposits_matched"], 1)
        self.assertEqual(attrs["benchmark.points"], len(DATES))
        # The symbol is deliberately absent: an unvalidated query param, so unbounded, and the
        # server span's own `http.url` already carries it.
        self.assertNotIn("benchmark.symbol", attrs)


if __name__ == "__main__":
    unittest.main()
