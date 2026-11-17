"""KAN-18 items 1-3: `get_prices()` across the whole provider chain.

Yahoo leads for every ticker; TwelveData and EODHD only top up what it missed. A
provider left unstubbed raises, so "this provider must not be called" is asserted
rather than assumed.
"""
import unittest
from unittest.mock import patch

import requests

from backend.app.core.config import settings
from backend.app.services import price_service
from test.support.stubs import EODHD_HOST, YAHOO_HOST, response, session_stub, yahoo_quote


class TestProviderOrdering(unittest.TestCase):
    def test_yahoo_prices_everything_without_touching_paid_providers(self):
        session, calls = session_stub(yahoo=lambda url, kw: response(payload=yahoo_quote(200.0)))
        with patch.object(price_service, "_session", session):
            prices, failures = price_service.get_prices(["AAPL", "MSFT", "PAY.L"])

        self.assertEqual(prices, {"AAPL": 200.0, "MSFT": 200.0, "PAY.L": 200.0})
        self.assertEqual(failures, [])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(YAHOO_HOST in url for url in calls))

    def test_lse_pence_quotes_are_converted_to_pounds(self):
        session, _ = session_stub(
            yahoo=lambda url, kw: response(payload=yahoo_quote(772.0, currency="GBp"))
        )
        with patch.object(price_service, "_session", session):
            prices, _failures = price_service.get_prices(["PAY.L"])

        self.assertAlmostEqual(prices["PAY.L"], 7.72)

    def test_yahoo_miss_falls_back_to_eodhd_and_stays_undegraded(self):
        session, calls = session_stub(
            yahoo=lambda url, kw: response(raise_exc=requests.HTTPError("429 Too Many Requests")),
            eodhd=lambda url, kw: response(payload={"close": 7.72}),
        )
        with patch.object(price_service, "_session", session), \
                patch.object(settings, "EODHD_API_TOKEN", "fake-token"):
            prices, failures = price_service.get_prices(["PAY.L"])

        self.assertAlmostEqual(prices["PAY.L"], 7.72)
        self.assertEqual([f["provider"] for f in failures], ["yahoo"])
        self.assertTrue(any(EODHD_HOST in url for url in calls))

    def test_eodhd_translates_the_yahoo_suffix(self):
        session, calls = session_stub(
            yahoo=lambda url, kw: response(raise_exc=requests.HTTPError("boom")),
            eodhd=lambda url, kw: response(payload={"close": 34.9}),
        )
        with patch.object(price_service, "_session", session), \
                patch.object(settings, "EODHD_API_TOKEN", "fake-token"):
            price_service.get_prices(["AFX.DE"])

        self.assertTrue(any("AFX.XETRA" in url for url in calls))


if __name__ == "__main__":
    unittest.main()
