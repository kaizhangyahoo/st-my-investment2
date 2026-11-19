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

    def test_default_is_the_total_of_stored_accounts(self):
        body = self.get()
        # QX2B3 is carried over its 01-03 gap; QRPOL only counts inside its own range.
        self.assertEqual(
            [(p["date"], p["value"]) for p in body["points"]],
            [("2024-01-02", 100.0), ("2024-01-03", 110.0), ("2024-01-04", 140.0), ("2024-01-05", 130.0)],
        )
        self.assertEqual(body["accounts"], ["QRPOL", "QX2B3"])
        self.assertIsNone(body["account_id"])
        self.assertFalse(body["data_quality"]["degraded"])
        self.assertTrue(body["computed_at"])

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
