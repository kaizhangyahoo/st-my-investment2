"""/api/v1/portfolio/metrics and /benchmark through the real FastAPI app (KAN-27).

Both endpoints exist to replace hardcoded dashboard figures, so what matters here is the
serialised body the client actually receives -- a field dropped by `response_model` filtering is
invisible to the type-checker and was how the last regression of this kind landed (KAN-49).

`/metrics` reads the stored values only and must never reach a price provider; `/benchmark`
does fetch, so its provider is stubbed rather than called.
"""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import pandas as pd

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - httpx/fastapi absent
    TestClient = None

from backend.app.core.config import settings
from backend.app.services import history_service

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


def _no_provider(*_args, **_kwargs):
    raise AssertionError("metrics must not hit a price provider")


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class MetricsCase(unittest.TestCase):
    def setUp(self):
        from backend.app.main import app

        self.tmpdir = tempfile.mkdtemp(prefix="verify_metrics_api_")
        self.values_path = os.path.join(self.tmpdir, "values.json")
        with open(self.values_path, "w") as f:
            json.dump(STORED, f)

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(settings, "PORTFOLIO_VALUES_FILE", self.values_path))
        stack.enter_context(patch.object(history_service, "get_price_history", _no_provider))
        stack.enter_context(patch.object(history_service, "get_historical_fx", _no_provider))
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


if __name__ == "__main__":
    unittest.main()
