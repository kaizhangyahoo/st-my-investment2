"""P2 split: portfolio-api calling data-api over HTTP gives the same answers as in-process.

The data-api side is the real `/internal` router mounted on a throwaway app; the HTTP hop is a
`TestClient` standing in for `PropagatingSession`, so nothing leaves the process. Providers are
stubbed underneath data-api, never on the client side, so the whole wire format is exercised.
"""
import unittest
from contextlib import ExitStack
from typing import List
from unittest.mock import patch

import pandas as pd
import requests

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

from backend.app.core.cache import cache
from backend.app.core.config import settings
from backend.app.services import data_client, history_service, market_service
from backend.app.services.ticker_service import load_ticker_mappings
from test.support.portfolio import TempMappingCase

BASE = "http://data-api.test"


class _Wire:
    """`PropagatingSession`'s surface, served by a TestClient; records every call."""

    def __init__(self, client: "TestClient"):
        self.client = client
        self.calls: List[str] = []

    def _path(self, url: str) -> str:
        assert url.startswith(BASE), url
        path = url[len(BASE):]
        self.calls.append(path)
        return path

    def get(self, url, params=None):
        return self.client.get(self._path(url), params=params)

    def post(self, url, json=None):
        return self.client.post(self._path(url), json=json)


class _Down:
    def get(self, url, **kw):
        raise requests.ConnectionError("refused")

    post = get


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class SplitCase(TempMappingCase):
    MAPPINGS = {"Apple Inc": "AAPL", "Vanguard S&P": "VUSA.L"}

    def setUp(self):
        super().setUp()
        from backend.app.api.v1 import internal

        cache.clear()
        self.addCleanup(cache.clear)
        app = FastAPI()
        app.include_router(internal.router, prefix=settings.API_V1_STR)
        self.wire = _Wire(TestClient(app))

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(settings, "DATA_API_URL", BASE))
        stack.enter_context(patch.object(data_client, "_http", lambda: self.wire))
        self.stack = stack
        self.assertTrue(data_client.remote())


class TestQuotes(SplitCase):
    def test_prices_and_failures_cross_the_wire_intact(self):
        failure = {"ticker": "BBB", "provider": "twelvedata", "reason": "429"}
        self.stack.enter_context(patch.object(
            market_service, "get_prices", lambda t: ({"AAA": 10.5, "BBB": None}, [failure])
        ))
        prices, failures = data_client.get_current_prices(["AAA", "BBB"])
        self.assertEqual(prices, {"AAA": 10.5, "BBB": None})
        self.assertEqual(failures, [failure])
        self.assertEqual(self.wire.calls, ["/api/v1/internal/quotes"])


class TestFx(SplitCase):
    def test_series_and_fallback_flag_round_trip(self):
        idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
        fx = {"GBPUSD=X": pd.Series([1.27, 1.28], index=idx),
              "GBPEUR=X": pd.Series([1.16, 1.17], index=idx)}
        from backend.app.api.v1 import internal
        self.stack.enter_context(patch.object(internal, "get_historical_fx", lambda s: (fx, True)))
        self.stack.enter_context(patch.object(internal, "fx_covered_through", lambda: "2024-01-03"))

        series, fallback = data_client.get_historical_fx("2024-01-01")
        self.assertTrue(fallback)
        for pair in fx:
            pd.testing.assert_series_equal(series[pair], fx[pair], check_freq=False, check_names=False)
        self.assertEqual(data_client.fx_covered_through(), "2024-01-03")


class TestPriceHistoryBatch(SplitCase):
    def test_history_makes_one_call_for_every_ticker(self):
        def yahoo(ticker, start):
            df = pd.DataFrame({"Date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                               "close": [1.0, 2.0]})
            df.attrs["currency"] = "USD" if ticker == "AAPL" else "GBp"
            return df
        self.stack.enter_context(patch.object(market_service, "fetch_yahoo_history", yahoo))

        closes, currencies, unpriced = history_service._price_frame(
            ["AAPL", "VUSA.L"], "2024-01-01"
        )
        self.assertEqual(self.wire.calls, ["/api/v1/internal/price-history"])
        self.assertEqual(currencies, {"AAPL": "USD", "VUSA.L": "GBp"})
        self.assertEqual(unpriced, [])
        self.assertEqual(list(closes["AAPL"].values), [1.0, 2.0])

    def test_an_unpriceable_ticker_comes_back_unpriced_not_zero(self):
        def yahoo(ticker, start):
            raise requests.ConnectionError("down")
        self.stack.enter_context(patch.object(market_service, "fetch_yahoo_history", yahoo))
        _, _, unpriced = history_service._price_frame(["DEAD"], "2024-01-01")
        self.assertEqual(unpriced, ["DEAD"])


class TestTickerMappings(SplitCase):
    def test_portfolio_side_reads_the_map_data_api_owns(self):
        # In one process both sides share `settings`, so the server-side read is pinned to the
        # map; otherwise data-api would see DATA_API_URL too and call itself.
        from backend.app.api.v1 import internal
        self.stack.enter_context(patch.object(internal, "load_ticker_mappings", lambda: self.MAPPINGS))
        load_ticker_mappings.clear()
        self.assertEqual(load_ticker_mappings(), self.MAPPINGS)
        self.assertEqual(self.wire.calls, ["/api/v1/internal/ticker-mappings"])


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestDataApiDown(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(settings, "DATA_API_URL", BASE))
        stack.enter_context(patch.object(data_client, "_http", lambda: _Down()))

    def test_prices_degrade_to_unpriced_with_a_recorded_failure(self):
        prices, failures = data_client.get_current_prices(["AAA"])
        self.assertEqual(prices, {"AAA": None})
        self.assertEqual(failures[0]["provider"], "data-api")

    def test_fx_degrades_to_flagged_fallback_with_no_coverage(self):
        _, fallback = data_client.get_historical_fx("2024-01-01")
        self.assertTrue(fallback)
        self.assertIsNone(data_client.fx_covered_through())

    def test_ticker_mappings_fail_loudly_rather_than_resolve_nothing(self):
        with self.assertRaises(requests.ConnectionError):
            data_client.fetch_ticker_mappings()


if __name__ == "__main__":
    unittest.main()
