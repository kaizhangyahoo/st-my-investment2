"""KAN-18: behaviour when a provider is exhausted or unreachable.

Degradation is a non-functional property here: the dashboard must still answer, and it
must announce that the figures are approximate rather than presenting them as real.
"""
import unittest
from unittest.mock import patch

import requests

from backend.app.core.cache import cache
from backend.app.core.config import settings
from backend.app.services import market_service, price_service
from test.support.portfolio import fx_frame, temp_fx_store
from test.support.stubs import response, session_stub, yahoo_history, yahoo_quote


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


class TestTransientFailureIsNotPinned(unittest.TestCase):
    """KAN-53: a provider blip must not outlive itself by the length of the cache TTL.

    Each of these fetchers is `@ttl_cache`'d and each used to fail by *returning* a value --
    an empty frame, the approximated rates, a map of Nones -- which the cache happily stored.
    One SSL error at the wrong moment then kept the dashboard degraded for an hour with no way
    to retry short of restarting the process, since nothing in `backend/` clears the cache.

    Driven through the stubbed HTTP session rather than by patching the fetchers, because what
    is being asserted is that the provider is *contacted again*, and a `yahoo=None` stub raises
    AssertionError -- which no production `except` clause catches -- if it is not.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        temp_fx_store(self)

    def call(self, fn, yahoo):
        session, calls = session_stub(yahoo=yahoo)
        with patch.object(price_service, "_session", session), \
                patch.object(settings, "EODHD_API_TOKEN", None):
            return fn(), calls

    def test_price_history_retries_after_the_provider_recovers(self):
        unreachable = requests.RequestException("SSLCertVerificationError")
        fetch = lambda: market_service.get_price_history("VUSA.L", "2024-01-01")

        (df, currency), failed = self.call(fetch, unreachable)
        self.assertTrue(df.empty)
        self.assertIsNone(currency)
        self.assertEqual(len(failed), 1)

        (df, currency), retried = self.call(fetch, lambda url, kw: response(payload=yahoo_history()))
        self.assertEqual(len(retried), 1, "the failure was cached, so the retry never happened")
        self.assertEqual(list(df["close"]), [100.0])
        self.assertEqual(currency, "USD")

    def test_fx_retries_rather_than_serving_the_approximated_rates_for_the_ttl(self):
        # The sharpest case: `history_service` *writes* the values it computes, and nothing is
        # stored beside them to say the rates were guessed, so a pinned fallback bakes a
        # several-percent error into the saved series permanently.
        unreachable = requests.RequestException("yahoo unreachable")
        fetch = lambda: market_service.get_historical_fx("2024-01-01")

        (_fx, fallback), _ = self.call(fetch, unreachable)
        self.assertTrue(fallback)

        def rates(url, kw):
            rate = 1.29 if "GBPUSD" in url else 1.15
            return response(payload=yahoo_history(closes=(rate,)))

        (fx, fallback), retried = self.call(fetch, rates)
        self.assertFalse(fallback, "the approximated rates were cached and served again")
        self.assertEqual(len(retried), 2)
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.29)

    def test_current_prices_retries_after_a_total_outage(self):
        unreachable = requests.RequestException("connection reset")
        fetch = lambda: market_service.get_current_prices(["PAY.L"])

        (prices, failures), _ = self.call(fetch, unreachable)
        self.assertIsNone(prices["PAY.L"])
        self.assertTrue(failures)

        quote = lambda url, kw: response(payload=yahoo_quote(250.0, currency="GBp"))
        (prices, _failures), retried = self.call(fetch, quote)
        self.assertEqual(len(retried), 1, "the outage was cached, so the portfolio stayed blank")
        self.assertAlmostEqual(prices["PAY.L"], 2.50)

    def test_a_successful_answer_is_still_cached(self):
        # The fix must not throw the baby out: without caching, every request re-fetches and
        # Yahoo starts 429ing, which is why the TTL exists at all.
        fetch = lambda: market_service.get_price_history("AAPL", "2024-01-01")
        self.call(fetch, lambda url, kw: response(payload=yahoo_history()))

        (df, _currency), second = self.call(fetch, None)
        self.assertEqual(second, [], "a cached success was re-fetched")
        self.assertEqual(list(df["close"]), [100.0])

    def test_an_empty_answer_from_a_reachable_provider_is_cached(self):
        # A delisted ticker legitimately has no closes. That is an answer, not a failure, and
        # retrying it on every request would spend the rate limit on a known-dead symbol.
        fetch = lambda: market_service.get_price_history("DEAD", "2024-01-01")
        empty = lambda url, kw: response(payload=yahoo_history(dates=(), closes=()))
        (df, _currency), _ = self.call(fetch, empty)
        self.assertTrue(df.empty)

        _result, second = self.call(fetch, None)
        self.assertEqual(second, [], "an empty-but-successful answer was re-fetched")


class TestFxFallback(unittest.TestCase):
    """KAN-18 item 5: approximated FX rates must announce themselves."""

    SEED = None

    def setUp(self):
        cache.clear()  # get_historical_fx is @ttl_cache'd on a shared module-level singleton
        self.addCleanup(cache.clear)
        self.store = temp_fx_store(self, seed=self.SEED)

    def fetch(self, yahoo):
        with patch.object(market_service, "fetch_yahoo_history", yahoo):
            return market_service.get_historical_fx("2024-01-01")

    def test_yahoo_failure_returns_the_fallback_flag(self):
        def boom(symbol, start_date, interval="1d"):
            raise requests.RequestException("yahoo unreachable")

        fx, fx_fallback = self.fetch(boom)

        self.assertTrue(fx_fallback)
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.25)
        self.assertAlmostEqual(float(fx["GBPEUR=X"].iloc[-1]), 1.15)

    def test_empty_series_counts_as_a_failure(self):
        def empty(symbol, start_date, interval="1d"):
            return fx_frame(1.29, dates=())

        _fx, fx_fallback = self.fetch(empty)

        self.assertTrue(fx_fallback)

    def test_real_rates_report_no_fallback(self):
        def ok(symbol, start_date, interval="1d"):
            return fx_frame(1.29 if symbol == "GBPUSD=X" else 1.15)

        fx, fx_fallback = self.fetch(ok)

        self.assertFalse(fx_fallback)
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.29)

    def test_one_dead_cross_degrades_the_whole_answer(self):
        # A valuation can hold both USD and EUR, so a half-real answer is not a clean one -- and
        # caching it would hold back the missing cross for the rest of the TTL.
        def half(symbol, start_date, interval="1d"):
            if symbol == "GBPEUR=X":
                raise requests.RequestException("yahoo unreachable")
            return fx_frame(1.29)

        _fx, fx_fallback = self.fetch(half)

        self.assertTrue(fx_fallback)


class TestFxOutageWithStoredHistory(TestFxFallback):
    """KAN-55: the approximated constants are a last resort, not the first fallback.

    `history_service` *persists* the values it computes and has nowhere to record that a rate was
    guessed, so an outage that falls back to 1.25 bakes a ~3% error into the saved series
    permanently. Once a real close has been stored, serving that is strictly better: it is a
    rate someone actually quoted, and the caller is still told the feed is degraded so the dates
    it does not cover can be withheld.
    """

    SEED = {
        "GBPUSD=X": {"2024-01-02": 1.27, "2024-01-03": 1.29},
        "GBPEUR=X": {"2024-01-02": 1.16, "2024-01-03": 1.17},
    }

    def test_yahoo_failure_returns_the_fallback_flag(self):
        def boom(symbol, start_date, interval="1d"):
            raise requests.RequestException("yahoo unreachable")

        fx, fx_fallback = self.fetch(boom)

        self.assertTrue(fx_fallback, "the feed is degraded even though the rates are real")
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.29)
        self.assertAlmostEqual(float(fx["GBPEUR=X"].iloc[-1]), 1.17)

    def test_empty_series_counts_as_a_failure(self):
        def empty(symbol, start_date, interval="1d"):
            return fx_frame(1.29, dates=())

        fx, fx_fallback = self.fetch(empty)

        self.assertTrue(fx_fallback)
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.29)

    def test_the_stored_history_reaches_the_caller_whole(self):
        def boom(symbol, start_date, interval="1d"):
            raise requests.RequestException("yahoo unreachable")

        fx, _fx_fallback = self.fetch(boom)

        self.assertEqual(
            [d.strftime("%Y-%m-%d") for d in fx["GBPUSD=X"].index],
            ["2024-01-02", "2024-01-03"],
        )

    def test_one_dead_cross_still_serves_the_other_from_the_fetch(self):
        def half(symbol, start_date, interval="1d"):
            if symbol == "GBPEUR=X":
                raise requests.RequestException("yahoo unreachable")
            return fx_frame(1.31, dates=("2024-01-04",))

        fx, fx_fallback = self.fetch(half)

        self.assertTrue(fx_fallback)
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.31)
        self.assertAlmostEqual(float(fx["GBPEUR=X"].iloc[-1]), 1.17)


if __name__ == "__main__":
    unittest.main()
