"""/api/v1/portfolio/metrics and /benchmark through the real FastAPI app (KAN-27, KAN-52).

Both endpoints exist to replace hardcoded dashboard figures, so what matters here is the
serialised body the client actually receives -- a field dropped by `response_model` filtering is
invisible to the type-checker and was how the last regression of this kind landed (KAN-49).

`/metrics` reads from two sources and must reach neither the filesystem nor a provider: the stored
value series, stubbed to a temp file, and the trade statement, which the live endpoint autoloads
from `~/Downloads` and which is therefore stubbed outright. `/benchmark` does fetch, so its
provider is stubbed rather than called.
"""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import pandas as pd
import requests

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - httpx/fastapi absent
    TestClient = None

from backend.app.core.cache import cache
from backend.app.core.config import settings
from backend.app.services import history_service, price_service
from test.support.stubs import response, session_stub, yahoo_history

# QX2B3 is the richer series, so it is the account both endpoints land on by default.
STORED = {
    "QX2B3": {
        "2024-01-02": 100.0,
        "2024-01-03": 110.0,
        "2024-01-04": 99.0,
        "2024-01-05": 120.0,
    },
    "QRPOL": {"2024-01-04": 20.0},
}

BENCHMARK_CLOSES = pd.DataFrame(
    {
        "Date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "close": [90.0, 91.0, 93.0],
    }
)

# The Schroders history from the real statement: one buy, a zero-cash split restating 100 shares as
# 585, a 13.29 fractional cash-out, a second buy, and the 2026 delisting paying 5310 for all 900.
# Realised P&L is 409.98 and anything else means the corporate actions were mis-read (KAN-52).
TRADE_COLUMNS = ["TextDate", "Time", "Activity", "Market", "Quantity", "Price", "Cost/Proceeds"]
TRADE_ROWS = [
    ("19-10-2026", "05:08:18", "CORPORATE ACTION", "Schroders PLC", -900.00, 590.00, 5310.00),
    ("30-08-2023", "09:20:43", "TRADE", "Schroders PLC", 315.00, 418.00, -1331.28),
    ("01-11-2022", "11:27:10", "CORPORATE ACTION", "Schroders PLC", -0.64, 2077.25, 13.29),
    ("01-11-2022", "11:27:10", "CORPORATE ACTION", "Schroders PLC", 0.64, 0.00, 0.00),
    ("20-09-2022", "07:32:08", "CORPORATE ACTION", "Schroders PLC", 585.00, 0.00, 0.00),
    ("20-09-2022", "07:30:49", "CORPORATE ACTION", "Schroders PLC", -117.00, 0.00, 0.00),
    ("20-09-2022", "06:23:52", "CORPORATE ACTION", "Schroders PLC", 17.00, 0.00, 0.00),
    ("21-05-2021", "15:37:09", "TRADE", "Schroders PLC", 100.00, 3548.00, -3568.74),
]
TICKER_MAP = {"Schroders PLC": "SDR.L"}
SOURCE_FILE = "TradeHistory-TEST.csv"


def _no_provider(*_args, **_kwargs):
    raise AssertionError("metrics must not hit a price provider")


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class MetricsCase(unittest.TestCase):
    # None stands for "no statement loaded", which is a separate branch of the response.
    TRADE_ROWS = TRADE_ROWS

    def setUp(self):
        from backend.app.main import app
        from backend.app.api.v1 import portfolio as portfolio_api

        self.tmpdir = tempfile.mkdtemp(prefix="verify_metrics_api_")
        self.values_path = os.path.join(self.tmpdir, "values.json")
        with open(self.values_path, "w") as f:
            json.dump(STORED, f)
        self.map_path = os.path.join(self.tmpdir, "tickers.json")
        with open(self.map_path, "w") as f:
            json.dump(TICKER_MAP, f)

        trade_df = (
            None
            if self.TRADE_ROWS is None
            else pd.DataFrame(self.TRADE_ROWS, columns=TRADE_COLUMNS)
        )

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(settings, "PORTFOLIO_VALUES_FILE", self.values_path))
        stack.enter_context(patch.object(settings, "TICKER_MAP_FILE", self.map_path))
        stack.enter_context(patch.object(history_service, "get_price_history", _no_provider))
        stack.enter_context(patch.object(history_service, "get_historical_fx", _no_provider))
        # The live endpoint scans ~/Downloads for the newest export, which would make these
        # assertions depend on whatever the developer last downloaded.
        stack.enter_context(
            patch.object(
                portfolio_api,
                "get_or_load_trade_df",
                lambda _user_id: (trade_df, None if trade_df is None else SOURCE_FILE),
            )
        )
        self.client = TestClient(app)

    def get(self, path, **params):
        r = self.client.get(f"/api/v1/portfolio/{path}", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class TestMetricsEndpoint(MetricsCase):
    def test_it_describes_the_same_account_history_would_return(self):
        body = self.get("metrics")
        self.assertEqual(body["account_id"], "QX2B3")
        self.assertEqual(body["account_id"], self.get("history")["account_id"])

    def test_every_timeframe_the_client_offers_survives_serialisation(self):
        windows = self.get("metrics")["windows"]
        self.assertEqual(sorted(windows), sorted(["1M", "3M", "6M", "1Y", "ALL"]))

    def test_the_figures_come_from_the_stored_series(self):
        all_window = self.get("metrics")["windows"]["ALL"]
        # 100 -> 120 is +20%, and the 110 -> 99 dip is a 10% drawdown.
        self.assertAlmostEqual(all_window["cumulative_return_pct"], 20.0, places=6)
        self.assertAlmostEqual(all_window["cumulative_return_gbp"], 20.0, places=6)
        self.assertAlmostEqual(all_window["max_drawdown_pct"], 10.0, places=6)
        self.assertGreater(all_window["annualised_volatility_pct"], 0.0)
        self.assertEqual(all_window["trading_days"], 4)

    def test_it_publishes_the_window_bounds_the_chart_filters_on(self):
        all_window = self.get("metrics")["windows"]["ALL"]
        self.assertEqual(all_window["start_date"], "2024-01-02")
        self.assertEqual(all_window["end_date"], "2024-01-05")

    def test_sharpe_reaches_the_client_as_null_not_as_a_number(self):
        for timeframe, metrics in self.get("metrics")["windows"].items():
            self.assertIn("sharpe_ratio", metrics, timeframe)
            self.assertIsNone(metrics["sharpe_ratio"], timeframe)

    def test_a_single_value_account_reports_nulls_rather_than_zeroes(self):
        all_window = self.get("metrics", account_id="QRPOL")["windows"]["ALL"]
        self.assertEqual(all_window["trading_days"], 1)
        self.assertIsNone(all_window["max_drawdown_pct"])
        self.assertIsNone(all_window["annualised_volatility_pct"])
        self.assertIsNone(all_window["cumulative_return_pct"])

    def test_an_unknown_account_is_empty_rather_than_an_error(self):
        body = self.get("metrics", account_id="NOSUCH")
        self.assertEqual(body["account_id"], "NOSUCH")
        self.assertEqual(body["windows"]["ALL"]["trading_days"], 0)
        self.assertIsNone(body["windows"]["ALL"]["start_date"])


class TestRealisedMetrics(MetricsCase):
    """The closed-trade half of the response, which backs the Win Rate tile (KAN-52)."""

    def realised(self, timeframe="ALL"):
        return self.get("metrics")["realised"][timeframe]

    def test_the_realised_block_survives_response_model_filtering(self):
        body = self.get("metrics")
        self.assertEqual(sorted(body["realised"]), sorted(["1M", "3M", "6M", "1Y", "ALL"]))
        self.assertEqual(
            sorted(self.realised()),
            sorted(
                [
                    "timeframe",
                    "start_date",
                    "end_date",
                    "disposals",
                    "winning_disposals",
                    "win_rate_pct",
                    "realised_pnl_gbp",
                ]
            ),
        )

    def test_win_rate_reaches_the_client_backed_by_per_disposal_pnl(self):
        all_window = self.realised()
        self.assertEqual(all_window["disposals"], 1)
        self.assertEqual(all_window["winning_disposals"], 1)
        self.assertAlmostEqual(all_window["win_rate_pct"], 100.0, places=6)

    def test_the_realised_figure_is_the_corporate_action_adjusted_one(self):
        self.assertAlmostEqual(self.realised()["realised_pnl_gbp"], 409.98, places=2)

    def test_realised_bounds_are_its_own_and_not_the_value_series(self):
        # The stored series ends 2024-01-05 and the statement ends 2026-10-19. A tile that borrowed
        # the curve's period would describe a window its own figures do not cover (KAN-27).
        body = self.get("metrics")
        self.assertEqual(body["realised"]["ALL"]["end_date"], "2026-10-19")
        self.assertEqual(body["windows"]["ALL"]["end_date"], "2024-01-05")

    def test_the_realised_figures_do_not_depend_on_which_account_is_asked_for(self):
        # The statement is the caller's own; `account_id` selects a stored value series, so it must
        # move `windows` without moving `realised`.
        other = self.get("metrics", account_id="QRPOL")
        self.assertAlmostEqual(other["realised"]["ALL"]["realised_pnl_gbp"], 409.98, places=2)
        self.assertEqual(other["windows"]["ALL"]["trading_days"], 1)

    def test_coverage_says_what_the_figures_were_computed_from(self):
        coverage = self.get("metrics")["realised_coverage"]
        self.assertEqual(coverage["source_file"], SOURCE_FILE)
        self.assertEqual(coverage["corporate_action_rows"], 6)
        self.assertAlmostEqual(coverage["corporate_action_cash_gbp"], 13.29, places=2)
        self.assertEqual(coverage["excluded_disposals"], 0)
        self.assertEqual(coverage["excluded_tickers"], [])
        self.assertIsNone(coverage["unavailable_reason"])

    def test_the_risk_tiles_are_unaffected_by_the_statement(self):
        # The two halves come from different sources; adding one must not disturb the other.
        all_window = self.get("metrics")["windows"]["ALL"]
        self.assertAlmostEqual(all_window["cumulative_return_pct"], 20.0, places=6)
        self.assertEqual(all_window["trading_days"], 4)


class TestRealisedWithoutAStatement(MetricsCase):
    TRADE_ROWS = None

    def test_no_statement_means_nulls_and_a_reason_rather_than_zeroes(self):
        body = self.get("metrics")
        for timeframe, window in body["realised"].items():
            self.assertEqual(window["disposals"], 0, timeframe)
            self.assertIsNone(window["win_rate_pct"], timeframe)
            self.assertIsNone(window["realised_pnl_gbp"], timeframe)
        self.assertIn("No trade statement", body["realised_coverage"]["unavailable_reason"])
        self.assertIsNone(body["realised_coverage"]["source_file"])

    def test_the_risk_tiles_still_work_without_a_statement(self):
        # A missing statement must blank the Win Rate tile only, not the whole row.
        self.assertAlmostEqual(
            self.get("metrics")["windows"]["ALL"]["cumulative_return_pct"], 20.0, places=6
        )


class TestRealisedWithNoClosedTrades(MetricsCase):
    """Someone who has bought and never sold. There is no win rate yet, and 0% is not it."""

    TRADE_ROWS = [row for row in TRADE_ROWS if row[4] > 0]

    def test_an_open_only_statement_reports_nulls_rather_than_zeroes(self):
        body = self.get("metrics")
        all_window = body["realised"]["ALL"]
        self.assertEqual(all_window["disposals"], 0)
        self.assertEqual(all_window["winning_disposals"], 0)
        self.assertIsNone(all_window["win_rate_pct"])
        self.assertIsNone(all_window["realised_pnl_gbp"])
        self.assertIsNone(all_window["start_date"])
        # The statement is loaded, so there is no reason to give -- just nothing closed yet.
        self.assertIsNone(body["realised_coverage"]["unavailable_reason"])
        self.assertEqual(body["realised_coverage"]["source_file"], SOURCE_FILE)


class TestBenchmarkEndpoint(MetricsCase):
    def benchmark(self, closes=BENCHMARK_CLOSES, currency="GBP", **params):
        with patch(
            "backend.app.api.v1.portfolio.get_price_history", return_value=(closes, currency)
        ) as fetch:
            body = self.get("benchmark", **params)
        return body, fetch

    def test_it_returns_the_fetched_closes_as_iso_dated_points(self):
        body, _ = self.benchmark()
        self.assertEqual(
            [(p["date"], p["value"]) for p in body["points"]],
            [("2024-01-02", 90.0), ("2024-01-03", 91.0), ("2024-01-04", 93.0)],
        )
        self.assertIsNone(body["unavailable_reason"])

    def test_the_default_symbol_is_the_gbp_quoted_tracker(self):
        body, fetch = self.benchmark()
        self.assertEqual(body["symbol"], "VUSA.L")
        self.assertEqual(fetch.call_args.args[0], "VUSA.L")
        self.assertEqual(body["currency"], "GBP")

    def test_a_caller_can_ask_for_another_symbol(self):
        body, fetch = self.benchmark(symbol="^GSPC")
        self.assertEqual(body["symbol"], "^GSPC")
        self.assertEqual(fetch.call_args.args[0], "^GSPC")

    def test_a_pence_quoted_tracker_is_passed_through_unconverted(self):
        # CNX1.L, the NASDAQ-100 comparison added in KAN-58, quotes in pence: ~112,600 against a
        # portfolio worth ~£45,000. Scaling it here would be wrong twice over, since the client
        # rebases onto its own opening value and that cancels the unit. The closes must arrive
        # raw with the currency named, not silently divided into something resembling pounds.
        pence = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "close": [26515.0, 112600.0],
            }
        )
        body, fetch = self.benchmark(closes=pence, currency="GBp", symbol="CNX1.L")
        self.assertEqual(fetch.call_args.args[0], "CNX1.L")
        self.assertEqual([p["value"] for p in body["points"]], [26515.0, 112600.0])
        self.assertEqual(body["currency"], "GBp")

    def test_values_are_raw_closes_so_the_client_can_rebase_per_timeframe(self):
        # Rebasing here would fix the comparison to the full series and silently mis-scale
        # every shorter window, so the server must not normalise.
        body, _ = self.benchmark()
        self.assertEqual(body["points"][0]["value"], 90.0)

    def test_an_unreachable_provider_yields_no_line_and_says_why(self):
        body, _ = self.benchmark(closes=pd.DataFrame(columns=["Date", "close"]), currency=None)
        self.assertEqual(body["points"], [])
        self.assertIn("VUSA.L", body["unavailable_reason"])

    def test_a_missing_close_is_dropped_rather_than_charted_as_zero(self):
        gappy = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "close": [90.0, float("nan")],
            }
        )
        body, _ = self.benchmark(closes=gappy)
        self.assertEqual([p["date"] for p in body["points"]], ["2024-01-02"])


class TestBenchmarkSurvivesATransientOutage(MetricsCase):
    """KAN-53 as it was reported: one SSL error against Yahoo turned the S&P 500 comparison
    off, and because the failure took the cache key the toggle stayed dead for an hour --
    nothing in `backend/` clears the cache, so only a restart brought the line back.

    The provider is stubbed at the HTTP session rather than at `get_price_history`, which the
    rest of this file patches out: the point is whether the fetch is attempted a second time.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def fetch(self, yahoo):
        session, calls = session_stub(yahoo=yahoo)
        with patch.object(price_service, "_session", session):
            return self.get("benchmark"), calls

    def test_the_comparison_line_comes_back_as_soon_as_the_provider_does(self):
        body, failed = self.fetch(requests.RequestException("SSLCertVerificationError"))
        self.assertEqual(body["points"], [])
        self.assertIn("VUSA.L", body["unavailable_reason"])
        self.assertEqual(len(failed), 1)

        body, retried = self.fetch(lambda url, kw: response(payload=yahoo_history()))
        self.assertEqual(len(retried), 1, "the failure was cached, so no retry was attempted")
        self.assertEqual([p["value"] for p in body["points"]], [100.0])
        self.assertIsNone(body["unavailable_reason"])


class TestMatchedBenchmarkEndpoint(MetricsCase):
    """`/benchmark/matched`, the comparison line fed by the account's own deposits (KAN-58).

    `/benchmark` hands the client raw closes to scale onto the curve, which silently means "one
    lump sum on day one" and re-means itself on every timeframe. This endpoint returns absolute
    GBP instead, so what matters here is that the deposits reaching it are the right account's and
    that nothing is charted when they cannot be trusted.
    """

    # Two deposits and a doubling, so the expected series is checkable without a spreadsheet.
    LEDGER = pd.DataFrame(
        {
            "TextDate": ["02/01/24", "03/01/24"],
            "Summary": ["Cash In", "Cash In"],
            "MarketName": ["Bank Deposit", "Bank Deposit"],
            "PL Amount": ["1,000.00", "500.00"],
            "DateUtc": ["2024-01-02T09:00:00", "2024-01-03T09:00:00"],
            "CurrencyIsoCode": ["GBP", "GBP"],
        }
    )
    LEDGER_FILE = "TransactionHistory-QX2B3-(01-11-2018)-(10-11-2026).csv"
    CLOSES = pd.DataFrame(
        {"Date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "close": [100.0, 200.0]}
    )

    # Distinct from None and from "", both of which are cases under test.
    DEFAULT = object()

    def matched(self, ledger=DEFAULT, filename=DEFAULT, currency="GBP", closes=None, **params):
        from backend.app.api.v1 import portfolio as portfolio_api

        df = self.LEDGER if ledger is self.DEFAULT else ledger
        source = self.LEDGER_FILE if filename is self.DEFAULT else filename
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    portfolio_api,
                    "get_or_load_transaction_df",
                    lambda _user_id: (df, source),
                )
            )
            fetch = stack.enter_context(
                patch(
                    "backend.app.api.v1.portfolio.get_price_history",
                    return_value=(self.CLOSES if closes is None else closes, currency),
                )
            )
            body = self.get("benchmark/matched", **params)
        return body, fetch

    def test_each_deposit_buys_at_its_own_close(self):
        body, _ = self.matched()
        # 1000 / 100 = 10 units, then 500 / 200 = 2.5 more: 12.5 x 200 = 2500. A lump sum would
        # have given 1500 x 2 = 3000, which is the comparison this replaces.
        self.assertEqual(
            [(p["date"], p["value"]) for p in body["points"]],
            [("2024-01-02", 1000.0), ("2024-01-03", 2500.0)],
        )
        self.assertIsNone(body["unavailable_reason"])

    def test_it_reports_what_it_was_fed_so_the_caption_can_say_so(self):
        body, _ = self.matched()
        self.assertEqual(body["deposits_matched"], 2)
        self.assertEqual(body["total_deposited_gbp"], 1500.0)
        self.assertEqual(body["first_deposit"], "2024-01-02")

    def test_the_values_are_absolute_gbp_and_not_rebased_onto_the_curve(self):
        # The stored series opens at 100.0. A first point of 100.0 here would mean the server had
        # scaled the line onto the curve, which is the fault being removed -- it must be the
        # deposit's own 1000.0.
        body, _ = self.matched()
        self.assertEqual(body["points"][0]["value"], 1000.0)
        self.assertEqual(self.get("history")["points"][0]["value"], 100.0)

    def test_closes_are_fetched_from_the_first_deposit_not_the_chart_window(self):
        # Fetching from a later window start would lose the units the early deposits bought, and
        # the line would begin partway up with no explanation.
        _, fetch = self.matched()
        self.assertEqual(fetch.call_args.args[1], "2024-01-02")

    def test_a_pence_quoted_tracker_lands_on_the_same_scale_as_a_pound_quoted_one(self):
        pence = pd.DataFrame(
            {"Date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "close": [10000.0, 20000.0]}
        )
        body, _ = self.matched(closes=pence, currency="GBp", symbol="CNX1.L")
        self.assertEqual(body["symbol"], "CNX1.L")
        self.assertEqual([p["value"] for p in body["points"]], [1000.0, 2500.0])

    def test_another_accounts_statement_is_not_charted_against_this_curve(self):
        # QRPOL has its own stored series, and QX2B3's deposits are not its contributions. Drawing
        # them would be wrong by the whole difference between two accounts, silently.
        body, _ = self.matched(account_id="QRPOL")
        self.assertEqual(body["points"], [])
        self.assertIn("QRPOL", body["unavailable_reason"])
        self.assertIn(self.LEDGER_FILE, body["unavailable_reason"])

    def test_an_upload_that_does_not_name_an_account_is_refused(self):
        # Without the account in the filename there is no way to confirm the deposits belong to
        # the series being drawn, and guessing favours a wrong line over no line.
        body, _ = self.matched(filename="")
        self.assertEqual(body["points"], [])
        self.assertIn("QX2B3", body["unavailable_reason"])

    def test_a_partial_export_yields_no_line_and_says_why(self):
        # The founding deposit is missing, so the running balance goes negative. Understated
        # deposits would make the index look beaten, which is the flattering direction.
        partial = pd.DataFrame(
            {
                "TextDate": ["02/01/24"],
                "Summary": ["Client Consideration"],
                "MarketName": ["Lam Research Corp CONS 2@100"],
                "PL Amount": ["-2,000.00"],
                "DateUtc": ["2024-01-02T09:00:00"],
                "CurrencyIsoCode": ["GBP"],
            }
        )
        body, _ = self.matched(ledger=partial)
        self.assertEqual(body["points"], [])
        self.assertIn("starts after the account did", body["unavailable_reason"])

    def test_a_statement_with_no_deposits_yields_no_line_and_says_why(self):
        none_external = self.LEDGER.assign(Summary=["Dividend", "Dividend"])
        body, _ = self.matched(ledger=none_external)
        self.assertEqual(body["points"], [])
        self.assertIn("No deposits found", body["unavailable_reason"])

    def test_no_statement_at_all_yields_no_line_and_says_why(self):
        body, _ = self.matched(ledger=None)
        self.assertEqual(body["points"], [])
        self.assertIn("No transaction statement", body["unavailable_reason"])

    def test_an_unreachable_provider_yields_no_line_and_says_why(self):
        body, _ = self.matched(closes=pd.DataFrame(columns=["Date", "close"]), currency=None)
        self.assertEqual(body["points"], [])
        self.assertIn("VUSA.L", body["unavailable_reason"])

    def test_a_usd_quoted_index_is_refused_rather_than_compared_without_fx(self):
        body, _ = self.matched(currency="USD", symbol="^GSPC")
        self.assertEqual(body["points"], [])
        self.assertIn("FX", body["unavailable_reason"])

    def test_the_lump_sum_endpoint_is_untouched_by_any_of_this(self):
        # `/benchmark` still returns raw closes for callers that rebase. Changing it would have
        # broken the meaning of a field rather than adding one.
        with patch(
            "backend.app.api.v1.portfolio.get_price_history",
            return_value=(BENCHMARK_CLOSES, "GBP"),
        ):
            body = self.get("benchmark")
        self.assertEqual(body["points"][0]["value"], 90.0)


if __name__ == "__main__":
    unittest.main()
