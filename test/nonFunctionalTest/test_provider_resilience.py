"""KAN-18: behaviour when a provider is exhausted or unreachable.

Degradation is a non-functional property here: the dashboard must still answer, and it
must announce that the figures are approximate rather than presenting them as real.
"""
import unittest
from unittest.mock import patch

import pandas as pd
import requests

from backend.app.core.cache import cache
from backend.app.core.config import settings
from backend.app.services import market_service, price_service
from test.support.stubs import response, session_stub


class TestEodhdQuotaExhaustion(unittest.TestCase):
    """The free tier 402s *every* symbol once the 20/day allowance is spent."""

    def test_402_names_the_quota_and_leaves_the_ticker_unpriced(self):
        session, _ = session_stub(
            yahoo=lambda url, kw: response(raise_exc=requests.HTTPError("boom")),
            eodhd=lambda url, kw: response(status=402),
        )
        with patch.object(price_service, "_session", session), \
                patch.object(settings, "EODHD_API_TOKEN", "fake-token"):
            prices, failures = price_service.get_prices(["PAY.L"])

        self.assertIsNone(prices["PAY.L"])
        eodhd_failures = [f for f in failures if f["provider"] == "eodhd"]
        self.assertEqual(len(eodhd_failures), 1)
        self.assertIn("20/day", eodhd_failures[0]["reason"])

    def test_one_dead_ticker_does_not_sink_the_others(self):
        """Failures are isolated per ticker, so a partial load is still a load."""
        def yahoo(url, kw):
            if "PAY.L" in url:
                raise requests.HTTPError("boom")
            return response(payload={
                "chart": {"result": [{"meta": {"regularMarketPrice": 200.0, "currency": "USD"}}]}
            })

        session, _ = session_stub(yahoo=yahoo)
        with patch.object(price_service, "_session", session), \
                patch.object(settings, "EODHD_API_TOKEN", None):
            prices, failures = price_service.get_prices(["AAPL", "PAY.L"])

        self.assertEqual(prices["AAPL"], 200.0)
        self.assertIsNone(prices["PAY.L"])
        self.assertTrue(failures)


class TestFxFallback(unittest.TestCase):
    """KAN-18 item 5: approximated FX rates must announce themselves."""

    def setUp(self):
        cache.clear()  # get_historical_fx is @ttl_cache'd on a shared module-level singleton

    tearDown = setUp

    def test_yahoo_failure_returns_the_fallback_flag(self):
        def boom(symbol, start_date, interval="1d"):
            raise requests.RequestException("yahoo unreachable")

        with patch.object(market_service, "fetch_yahoo_history", boom):
            fx, fx_fallback = market_service.get_historical_fx("2024-01-01")

        self.assertTrue(fx_fallback)
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.25)
        self.assertAlmostEqual(float(fx["GBPEUR=X"].iloc[-1]), 1.15)

    def test_empty_series_counts_as_a_failure(self):
        def empty(symbol, start_date, interval="1d"):
            return pd.DataFrame({"close": pd.Series(dtype="float64")})

        with patch.object(market_service, "fetch_yahoo_history", empty):
            _fx, fx_fallback = market_service.get_historical_fx("2024-01-01")

        self.assertTrue(fx_fallback)

    def test_real_rates_report_no_fallback(self):
        def ok(symbol, start_date, interval="1d"):
            rate = 1.29 if symbol == "GBPUSD=X" else 1.15
            return pd.DataFrame({"close": [rate]})

        with patch.object(market_service, "fetch_yahoo_history", ok):
            fx, fx_fallback = market_service.get_historical_fx("2024-01-01")

        self.assertFalse(fx_fallback)
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.29)


if __name__ == "__main__":
    unittest.main()
