"""/api/v1/portfolio/history through the real FastAPI app.

Two halves:
- GET  /history          (KAN-39) reads `user_portfolio_values.json` only. It must never hit a
  price provider, so a provider gap (e.g. delisted tickers) cannot blank the chart.
- POST /history/compute  (KAN-19) values the uploaded trade history and persists it to the
  JSON without clobbering the legacy Trading 212 keys.
"""
import io
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

STORED = {
    "QX2B3": {"2024-01-02": 100.0, "2024-01-04": 120.0, "2024-01-05": 130.0},
    "QRPOL": {"2024-01-03": 10.0, "2024-01-04": 20.0},
}


def _no_provider(*_args, **_kwargs):
    raise AssertionError("history must not hit a price provider")


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestHistoryEndpoint(unittest.TestCase):
    def setUp(self):
        from backend.app.main import app

        self.tmpdir = tempfile.mkdtemp(prefix="verify_history_api_")
        self.values_path = os.path.join(self.tmpdir, "values.json")
        with open(self.values_path, "w") as f:
            json.dump(STORED, f)

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(settings, "PORTFOLIO_VALUES_FILE", self.values_path))
        stack.enter_context(patch.object(history_service, "get_price_history", _no_provider))
        stack.enter_context(patch.object(history_service, "get_historical_fx", _no_provider))
        self.client = TestClient(app)

    def get(self, **params):
        r = self.client.get("/api/v1/portfolio/history", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_default_is_the_richest_account_not_a_total(self):
        body = self.get()
        self.assertEqual(
            [(p["date"], p["value"]) for p in body["points"]],
            [("2024-01-02", 100.0), ("2024-01-04", 120.0), ("2024-01-05", 130.0)],
        )
        self.assertEqual(body["account_id"], "QX2B3")
        self.assertEqual(body["accounts"], ["QRPOL", "QX2B3"])
        self.assertFalse(body["data_quality"]["degraded"])
        self.assertTrue(body["computed_at"])

    def test_no_response_point_ever_sums_across_accounts(self):
        """KAN-46: the stored accounts are not one person's, and two of them were the same
        account written by both apps, so a summed point was ~2x a portfolio nobody held."""
        for account_id in (None, "QX2B3", "QRPOL"):
            with self.subTest(account_id):
                points = self.get(**({"account_id": account_id} if account_id else {}))["points"]
                self.assertEqual(
                    {p["date"]: p["value"] for p in points},
                    STORED[account_id or "QX2B3"],
                    "series must be one account verbatim",
                )

    def test_consolidation_helper_is_gone(self):
        self.assertFalse(hasattr(history_service, "read_consolidated_series"))

    def test_no_gap_is_offered_for_an_account_this_backend_cannot_write(self):
        # Recomputing writes the caller's own "ig:" key, so offering it on a legacy account
        # would be a button that cannot do what it says.
        for account_id in (None, "QX2B3", "QRPOL"):
            with self.subTest(account_id):
                body = self.get(**({"account_id": account_id} if account_id else {}))
                self.assertFalse(body["fillable_gap"])

    def test_a_gap_is_offered_on_the_callers_own_stale_account(self):
        history_service._merge_and_write("ig:default", {"2024-01-02": 5.0})
        body = self.get(account_id="ig:default")
        self.assertTrue(body["fillable_gap"])

    def test_an_empty_file_offers_the_caller_their_own_account(self):
        os.remove(self.values_path)
        body = self.get()
        self.assertEqual(body["account_id"], "ig:default")
        self.assertEqual(body["points"], [])
        self.assertTrue(body["fillable_gap"])

    def test_account_id_reads_a_stored_series_verbatim(self):
        body = self.get(account_id="QRPOL")
        self.assertEqual(
            body["points"],
            [{"date": "2024-01-03", "value": 10.0}, {"date": "2024-01-04", "value": 20.0}],
        )
        self.assertEqual(body["account_id"], "QRPOL")

    def test_unknown_account_id_returns_empty(self):
        self.assertEqual(self.get(account_id="NOPE")["points"], [])

    def test_reading_does_not_rewrite_the_file(self):
        self.get()
        with open(self.values_path) as f:
            self.assertEqual(json.load(f), STORED)

    def test_missing_file_returns_empty(self):
        os.remove(self.values_path)
        body = self.get()
        self.assertEqual(body["points"], [])
        self.assertEqual(body["accounts"], [])


DATES = ["2024-01-02", "2024-01-03"]
TRADE_CSV = "Market,Quantity,Date\nApple Inc,10,2024-01-02\n"


def _fx(_start):
    idx = pd.to_datetime(DATES)
    return {
        "GBPUSD=X": pd.Series([2.0, 2.0], index=idx),
        "GBPEUR=X": pd.Series([1.25, 1.25], index=idx),
    }, False


def _prices(ticker, _start):
    if ticker != "AAPL":
        return pd.DataFrame(columns=["Date", "close"]), None
    return pd.DataFrame({"Date": pd.to_datetime(DATES), "close": [100.0, 120.0]}), "USD"


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestHistoryComputeEndpoint(unittest.TestCase):
    def setUp(self):
        from backend.app.api.v1 import trades
        from backend.app.main import app

        self.tmpdir = tempfile.mkdtemp(prefix="verify_history_compute_")
        map_path = os.path.join(self.tmpdir, "ticker_map.json")
        self.values_path = os.path.join(self.tmpdir, "values.json")
        with open(map_path, "w") as f:
            json.dump({"Apple Inc": "AAPL"}, f)
        # A Trading 212 series the legacy Streamlit app would have written.
        with open(self.values_path, "w") as f:
            json.dump({"QX2B3": {"2019-04-30": 1234.5}}, f)

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(settings, "TICKER_MAP_FILE", map_path))
        from backend.app.services.ticker_service import load_ticker_mappings
        load_ticker_mappings.clear()
        self.addCleanup(load_ticker_mappings.clear)
        stack.enter_context(patch.object(settings, "PORTFOLIO_VALUES_FILE", self.values_path))
        stack.enter_context(patch.object(history_service, "get_price_history", _prices))
        stack.enter_context(patch.object(history_service, "get_historical_fx", _fx))
        # No bearer token means get_current_user's dev fallback, which has no "sub".
        stack.enter_context(patch.dict(
            trades._LAST_TRADE_DF, {"default": pd.read_csv(io.StringIO(TRADE_CSV))}, clear=True
        ))
        stack.enter_context(patch.dict(trades._LAST_TRANSACTION_DF, {}, clear=True))
        self.client = TestClient(app)

    def compute(self, **params):
        r = self.client.post("/api/v1/portfolio/history/compute", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_returns_the_computed_series_for_the_uploaded_portfolio(self):
        body = self.compute()
        self.assertEqual(
            [(p["date"], p["value"]) for p in body["points"]],
            [("2024-01-02", 500.0), ("2024-01-03", 600.0)],
        )
        self.assertFalse(body["data_quality"]["degraded"])
        self.assertEqual(body["account_id"], "ig:default")

    def test_computed_series_is_persisted_without_clobbering_the_legacy_keys(self):
        self.compute()
        with open(self.values_path) as f:
            stored = json.load(f)
        self.assertEqual(stored["QX2B3"], {"2019-04-30": 1234.5})
        self.assertEqual(sorted(stored["ig:default"]), DATES)

    def test_get_reads_back_what_compute_stored(self):
        self.compute()
        r = self.client.get("/api/v1/portfolio/history", params={"account_id": "ig:default"})
        self.assertEqual(
            [(p["date"], p["value"]) for p in r.json()["points"]],
            [("2024-01-02", 500.0), ("2024-01-03", 600.0)],
        )

    def test_no_trade_history_returns_empty_and_writes_nothing(self):
        from backend.app.api.v1 import trades
        with patch.dict(trades._LAST_TRADE_DF, {}, clear=True), \
             patch.object(trades, "find_latest_download_files", lambda: (None, None)):
            self.assertEqual(self.compute()["points"], [])
        with open(self.values_path) as f:
            self.assertEqual(json.load(f), {"QX2B3": {"2019-04-30": 1234.5}})


if __name__ == "__main__":
    unittest.main()
