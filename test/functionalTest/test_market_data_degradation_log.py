"""The /api/v1/market-data routes recorded nothing when a provider failed.

Both bound a degradation signal -- the price failure list, the FX fallback flag -- and dropped
it on the floor, so a null price in the browser had no server-side counterpart once the tab was
closed. Driven over HTTP rather than by calling the handlers directly, because the point is
that adding the log line left the response untouched.

`log_data_quality`'s three branches are asserted apart here: unpriced is a WARNING, a failure a
fallback covered is an INFO, and a clean answer a DEBUG. The FX route is the one that matters
most -- it serves invented constants as if they were closes (KAN-62), which until now it did
silently.
"""
import json
import logging
import unittest
from unittest.mock import patch

import pandas as pd

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - httpx/fastapi absent
    TestClient = None

from backend.app.api.v1 import market_data
from backend.app.core import redaction
from backend.app.core.logging_config import JsonFormatter

LOGGER = "backend.app.api.v1.market_data"
FX = {"GBPUSD=X": pd.Series([1.29], index=pd.to_datetime(["2024-01-02"]))}


class _Case(unittest.TestCase):
    def setUp(self):
        from backend.app.main import app

        self.client = TestClient(app)


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestQuotesDegradationLog(_Case):
    def _get(self, prices, failures=()):
        with patch.object(market_data, "get_current_prices", lambda t: (prices, list(failures))):
            with self.assertLogs(LOGGER, logging.DEBUG) as captured:
                res = self.client.get("/api/v1/market-data/quotes", params={"tickers": "AAA,BBB"})
        self.assertEqual(res.status_code, 200)
        # The line is a read of the answer, not a change to it.
        self.assertEqual(res.json(), prices)
        self.assertEqual(len(captured.records), 1)
        return captured.records[0]

    def test_an_unpriced_ticker_is_a_warning_naming_the_consequence(self):
        record = self._get({"AAA": 200.0, "BBB": None})

        self.assertEqual(record.levelno, logging.WARNING)
        self.assertIn("market_data.quotes", record.getMessage())
        self.assertIn("understated", record.getMessage())
        self.assertEqual(record.unpriced_tickers, ["BBB"])
        self.assertEqual(record.surface, "market_data.quotes")

    def test_a_failure_a_fallback_covered_is_an_info_not_an_alarm(self):
        failure = {"ticker": "BBB", "provider": "yahoo", "reason": "no regularMarketPrice"}
        record = self._get({"AAA": 200.0, "BBB": 7.72}, failures=[failure])

        self.assertEqual(record.levelno, logging.INFO)
        self.assertIn("recovered", record.getMessage())
        self.assertEqual(record.failure_count, 1)

    def test_a_clean_answer_is_a_debug_line_and_nothing_louder(self):
        record = self._get({"AAA": 200.0, "BBB": 7.72})

        self.assertEqual(record.levelno, logging.DEBUG)
        self.assertEqual(record.unpriced_tickers, [])

    def test_a_failure_reason_carrying_a_provider_key_is_redacted_on_the_way_to_stdout(self):
        """The real leak this closes. `_failure(..., str(e))` on a requests error embeds the
        whole URL, so the reason reaching `extra` carries the key the request was made with."""
        secret = "td-live-key-9f3a1c"
        redaction.set_secret_literals([secret])
        self.addCleanup(redaction.set_secret_literals, [])
        failure = {
            "ticker": "BBB", "provider": "twelvedata",
            "reason": f"request failed: GET https://api.twelvedata.com/eod?apikey={secret}",
        }

        record = self._get({"AAA": 200.0, "BBB": None}, failures=[failure])
        line = json.loads(JsonFormatter("test-project").format(record))

        self.assertNotIn(secret, line["message"])
        self.assertNotIn(secret, json.dumps(line))
        self.assertIn("[redacted]", line["context"]["failures"][0]["reason"])


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestFxFallbackLog(_Case):
    def _get(self, fallback):
        with patch.object(market_data, "get_historical_fx", lambda start: (FX, fallback)):
            with self.assertLogs(LOGGER, logging.DEBUG) as captured:
                res = self.client.get("/api/v1/market-data/fx")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(list(res.json()), ["GBPUSD=X"])
        self.assertEqual(len(captured.records), 1)
        return captured.records[0]

    def test_serving_the_fallback_rates_is_a_warning_that_says_they_are_estimates(self):
        record = self._get(True)

        self.assertEqual(record.levelno, logging.WARNING)
        self.assertIn("market_data.fx", record.getMessage())
        self.assertIn("estimates, not real quotes", record.getMessage())
        self.assertIs(record.fx_fallback, True)

    def test_a_real_fx_answer_is_a_debug_line(self):
        record = self._get(False)

        self.assertEqual(record.levelno, logging.DEBUG)
        self.assertIs(record.fx_fallback, False)


if __name__ == "__main__":
    unittest.main()
