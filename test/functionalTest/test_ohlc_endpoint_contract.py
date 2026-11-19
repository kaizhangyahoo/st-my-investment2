"""GET /api/v1/market-data/ohlc/{ticker} response contract, through the real app.

KAN-37: the endpoint moved from a bare records list to `{ticker, currency, points}` with
nothing guarding it. KAN-35: `get_ohlc` is now `@ttl_cache`-wrapped, so the caching
behaviour is asserted here too -- including that a provider *failure* is not cached, which
is the whole point of caching an endpoint that exists to survive Yahoo's rate limiting.

Driven over HTTP rather than by calling the handler directly, because the NaN assertion is
about JSON serialisation: a handler call returns a dict and would pass even if the payload
could not be encoded.
"""
import unittest
from unittest.mock import patch

import pandas as pd
import requests

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - httpx/fastapi absent
    TestClient = None

from backend.app.core.cache import cache
from backend.app.services import price_service
from test.support.stubs import YAHOO_HOST, response, session_stub

DATES = ["2024-01-02", "2024-01-03"]
START = "2023-01-01"


def epochs(dates):
    return [int(pd.Timestamp(d, tz="UTC").timestamp()) for d in dates]


def chart(dates=DATES, closes=(100.0, 120.0), currency="USD", **extra_cols):
    """A Yahoo /v8/finance/chart payload. `extra_cols` fills the open/high/volume arrays
    that the handler deliberately drops."""
    quote = {"close": list(closes), **{k: list(v) for k, v in extra_cols.items()}}
    return {"chart": {"result": [{
        "meta": {"currency": currency},
        "timestamp": epochs(dates),
        "indicators": {"quote": [quote]},
    }]}}


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestOhlcEndpointContract(unittest.TestCase):
    def setUp(self):
        from backend.app.main import app

        # market_service's fetchers are wrapped in one module-level ttl_cache singleton with
        # no cache_clear(), so it has to be emptied either side of every test.
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = TestClient(app)

    def get(self, ticker="AAPL", yahoo=None, start_date=START):
        session, calls = session_stub(yahoo=yahoo)
        with patch.object(price_service, "_session", session):
            r = self.client.get(
                f"/api/v1/market-data/ohlc/{ticker}", params={"start_date": start_date}
            )
        self.assertEqual(r.status_code, 200, r.text)
        return r, calls

    def test_response_is_ticker_currency_and_dated_closes(self):
        r, _ = self.get(yahoo=lambda url, kw: response(payload=chart()))
        body = r.json()

        self.assertEqual(sorted(body), ["currency", "points", "ticker"])
        self.assertEqual(body["ticker"], "AAPL")
        self.assertEqual(body["currency"], "USD")
        self.assertEqual(
            body["points"],
            [{"date": "2024-01-02", "close": 100.0}, {"date": "2024-01-03", "close": 120.0}],
        )
        for p in body["points"]:
            self.assertIsInstance(p["close"], float)

    def test_nan_in_the_dropped_columns_still_serialises(self):
        # open/high/volume are why the handler emits only Date/close: NaN is not valid JSON.
        r, _ = self.get(yahoo=lambda url, kw: response(payload=chart(
            open=[None, 5.0], high=[None, None], volume=[None, 100],
        )))

        self.assertNotIn("NaN", r.text)
        self.assertEqual([p["close"] for p in r.json()["points"]], [100.0, 120.0])

    def test_a_row_with_no_close_is_omitted_rather_than_sent_as_null(self):
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        r, _ = self.get(yahoo=lambda url, kw: response(
            payload=chart(dates=dates, closes=(100.0, None, 120.0))
        ))

        self.assertNotIn("null", r.text)
        self.assertEqual(
            [p["date"] for p in r.json()["points"]], ["2024-01-02", "2024-01-04"]
        )

    def test_unreachable_ticker_is_empty_points_not_an_error(self):
        r, _ = self.get(ticker="NOPE", yahoo=requests.HTTPError("429 Too Many Requests"))

        self.assertEqual(r.json(), {"ticker": "NOPE", "currency": None, "points": []})

    def test_quote_currency_passes_through_from_frame_attrs(self):
        # Survives only because get_ohlc returns the frame unmodified -- pandas drops .attrs
        # across most operations, and the chart's y-axis label reads this.
        r, _ = self.get(ticker="PAY.L", yahoo=lambda url, kw: response(
            payload=chart(currency="GBp")
        ))

        self.assertEqual(r.json()["currency"], "GBp")

    def test_repeat_request_for_the_same_series_does_not_refetch(self):
        payload = chart()
        _, first = self.get(yahoo=lambda url, kw: response(payload=payload))
        self.assertEqual(len(first), 1)
        self.assertTrue(all(YAHOO_HOST in url for url in first))

        # yahoo=None in the stub means "must not be called" and raises AssertionError, which
        # no production except clause catches -- so a cache miss fails loudly here.
        r, second = self.get()
        self.assertEqual(second, [])
        self.assertEqual(r.json()["currency"], "USD")
        self.assertEqual(len(r.json()["points"]), 2)

    def test_cache_key_separates_start_dates(self):
        self.get(yahoo=lambda url, kw: response(payload=chart()))
        _, calls = self.get(
            start_date="2020-06-01", yahoo=lambda url, kw: response(payload=chart())
        )

        self.assertEqual(len(calls), 1)

    def test_a_provider_failure_is_retried_rather_than_cached(self):
        _, failed = self.get(yahoo=requests.HTTPError("429 Too Many Requests"))
        self.assertEqual(len(failed), 1)

        r, retried = self.get(yahoo=lambda url, kw: response(payload=chart()))
        self.assertEqual(len(retried), 1, "the 429 was cached, so the retry never happened")
        self.assertEqual([p["close"] for p in r.json()["points"]], [100.0, 120.0])


if __name__ == "__main__":
    unittest.main()
