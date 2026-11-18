"""KAN-18: single-provider response handling, with no orchestration in the way."""
import unittest
from unittest.mock import patch

from backend.app.core.config import settings
from backend.app.services import price_service
from test.support.stubs import response, session_stub


class TestEodhdCloseHandling(unittest.TestCase):
    """KAN-18 item 6: `close or previousClose` wrongly treated a genuine 0.0 as missing.
    KAN-28: LSE quotes in pence must be converted to GBP.
    """

    def _fetch(self, payload, ticker="PAY.L"):
        session, _ = session_stub(eodhd=lambda url, kw: response(payload=payload))
        with patch.object(price_service, "_session", session), \
                patch.object(settings, "EODHD_API_TOKEN", "fake-token"):
            return price_service.fetch_eodhd_price(ticker)

    def test_genuine_zero_close_is_preserved(self):
        self.assertEqual(self._fetch({"close": 0.0, "previousClose": 772.0}), 0.0)

    def test_absent_close_falls_back_to_previous_close(self):
        self.assertAlmostEqual(self._fetch({"previousClose": 772.0}), 7.72)

    def test_lse_pence_quote_is_converted_to_pounds(self):
        self.assertAlmostEqual(self._fetch({"close": 1234.5}, ticker="PAY.L"), 12.345)

    def test_non_lse_quote_is_not_divided(self):
        self.assertAlmostEqual(self._fetch({"close": 34.9}, ticker="AFX.DE"), 34.9)

    def test_missing_token_raises_before_any_http(self):
        session, calls = session_stub()
        with patch.object(price_service, "_session", session), \
                patch.object(settings, "EODHD_API_TOKEN", None):
            with self.assertRaises(ValueError):
                price_service.fetch_eodhd_price("PAY.L")
        self.assertEqual(calls, [])


class TestTwelvedataConfig(unittest.TestCase):
    def test_missing_key_reports_a_failure_without_any_http(self):
        session, calls = session_stub()
        with patch.object(price_service, "_session", session), \
                patch.object(price_service, "_twelvedata_keys", lambda: []):
            prices, failures = price_service.fetch_us_prices(["AAPL"])

        self.assertEqual(prices, {})
        self.assertEqual(calls, [])
        self.assertIn("not set", failures[0]["reason"])


if __name__ == "__main__":
    unittest.main()
