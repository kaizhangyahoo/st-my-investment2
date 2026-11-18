"""GET /api/v1/portfolio/history through the real FastAPI app, with every provider patched.

Covers the KAN-19 regression directly: the endpoint used to read `user_portfolio_values.json`
and return whatever the Streamlit app last wrote, so an uploaded portfolio could not change it.
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
class TestHistoryEndpoint(unittest.TestCase):
    def setUp(self):
        from backend.app.api.v1 import trades
        from backend.app.main import app

        self.tmpdir = tempfile.mkdtemp(prefix="verify_history_api_")
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

    def get(self, **params):
        r = self.client.get("/api/v1/portfolio/history", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_returns_the_computed_series_for_the_uploaded_portfolio(self):
        body = self.get()
        self.assertEqual(
            [(p["date"], p["value"]) for p in body["points"]],
            [("2024-01-02", 500.0), ("2024-01-03", 600.0)],
        )
        self.assertFalse(body["data_quality"]["degraded"])
        self.assertTrue(body["computed_at"])

    def test_computed_series_is_persisted_without_clobbering_the_legacy_keys(self):
        self.get()
        with open(self.values_path) as f:
            stored = json.load(f)
        self.assertEqual(stored["QX2B3"], {"2019-04-30": 1234.5})
        self.assertEqual(sorted(stored["ig:default"]), DATES)

    def test_account_id_reads_a_stored_series_verbatim(self):
        body = self.get(account_id="QX2B3")
        self.assertEqual(body["points"], [{"date": "2019-04-30", "value": 1234.5}])

    def test_unknown_account_id_returns_empty_rather_than_the_callers_series(self):
        self.assertEqual(self.get(account_id="NOPE")["points"], [])

    def test_no_trade_history_returns_empty_not_a_stale_series(self):
        from backend.app.api.v1 import trades
        with patch.dict(trades._LAST_TRADE_DF, {}, clear=True), \
             patch.object(trades, "find_latest_download_files", lambda: (None, None)):
            self.assertEqual(self.get()["points"], [])


if __name__ == "__main__":
    unittest.main()
