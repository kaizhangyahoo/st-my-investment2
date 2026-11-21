"""KAN-18: behaviour when a provider is exhausted or unreachable.

Degradation is a non-functional property here: the dashboard must still answer, and it
must announce that the figures are approximate rather than presenting them as real.
"""
import unittest
from unittest.mock import patch

import requests

from backend.app.core.cache import cache
from backend.app.core.config import settings
from backend.app.services import market_service, portfolio_engine, price_service
from test.support.portfolio import TempMappingCase, fx_frame, temp_fx_store, trade_df
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


class TestPricesAreCachedPerTicker(unittest.TestCase):
    """KAN-54: one ticker's blip must not take the rest of the portfolio down with it.

    `get_current_prices` was memoised on the whole requested list, so a single transient
    failure was stored beside thirty good prices and served for the rest of the TTL, and any
    change to the position set discarded prices that were still perfectly valid.

    Driven through the stubbed session rather than by patching the fetchers, because the
    assertion is about which tickers are *contacted*: a `yahoo=None` stub raises
    AssertionError -- which no production `except` clause catches -- if a cached price is
    re-fetched, and a missing retry shows up as an absent URL.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    @staticmethod
    def quotes(priced):
        """Yahoo handler pricing the tickers in `priced`; anything else is unreachable."""
        def yahoo(url, kw):
            for ticker, price in priced.items():
                if ticker in url:
                    return response(payload=yahoo_quote(price))
            raise requests.RequestException("connection reset")
        return yahoo

    def fetch(self, tickers, yahoo, twelvedata=None, key=None):
        session, calls = session_stub(yahoo=yahoo, twelvedata=twelvedata)
        with patch.object(price_service, "_session", session), \
                patch.object(settings, "EODHD_API_TOKEN", None), \
                patch.object(settings, "TWELVEDATA_API_KEY", key):
            return market_service.get_current_prices(tickers), calls

    def contacted(self, calls, ticker):
        return [url for url in calls if ticker in url]

    def test_a_failed_ticker_is_retried_while_the_others_stay_cached(self):
        # The whole defect in one test: NVDA blips, AAPL and MSFT do not, and the next request
        # must re-contact NVDA *only*.
        (prices, _f), first = self.fetch(
            ["AAPL", "MSFT", "NVDA"], self.quotes({"AAPL": 200.0, "MSFT": 400.0})
        )
        self.assertEqual(len(first), 3)
        self.assertIsNone(prices["NVDA"])

        (prices, _f), retry = self.fetch(
            ["AAPL", "MSFT", "NVDA"], self.quotes({"AAPL": 999.0, "MSFT": 999.0, "NVDA": 500.0})
        )

        self.assertEqual(len(retry), 1, "the blip was cached, so NVDA was never retried")
        self.assertTrue(self.contacted(retry, "NVDA"))
        self.assertEqual(prices["NVDA"], 500.0)
        # Served from cache, so the 999.0 the stub now offers must not reach the caller.
        self.assertEqual(prices["AAPL"], 200.0)
        self.assertEqual(prices["MSFT"], 400.0)

    def test_a_cached_price_is_not_refetched(self):
        # Without this the TTL buys nothing and Yahoo starts 429ing, which is the whole reason
        # the cache exists.
        self.fetch(["AAPL"], self.quotes({"AAPL": 200.0}))

        (prices, failures), second = self.fetch(["AAPL"], None)

        self.assertEqual(second, [], "a cached price was re-fetched")
        self.assertEqual(prices["AAPL"], 200.0)
        self.assertEqual(failures, [])

    def test_reordering_the_list_reuses_every_cached_price(self):
        # `/market-data/quotes?tickers=A,B` and `?tickers=B,A` were separate keys, each
        # re-fetching both tickers.
        self.fetch(["AAPL", "MSFT"], self.quotes({"AAPL": 200.0, "MSFT": 400.0}))

        (prices, _f), second = self.fetch(["MSFT", "AAPL"], None)

        self.assertEqual(second, [], "reordering the list re-fetched prices already held")
        self.assertEqual(prices, {"MSFT": 400.0, "AAPL": 200.0})

    def test_adding_one_position_fetches_only_that_position(self):
        # `calculate_positions_from_df` drops positions that net to zero, so one new trade used
        # to change the key and invalidate the prices for the entire portfolio.
        self.fetch(["AAPL", "MSFT"], self.quotes({"AAPL": 200.0, "MSFT": 400.0}))

        (prices, _f), second = self.fetch(
            ["AAPL", "MSFT", "NVDA"], self.quotes({"NVDA": 500.0})
        )

        self.assertEqual(len(second), 1, "adding one ticker re-fetched the ones already cached")
        self.assertTrue(self.contacted(second, "NVDA"))
        self.assertEqual(prices, {"AAPL": 200.0, "MSFT": 400.0, "NVDA": 500.0})

    def test_failures_describe_this_request_not_a_cached_one(self):
        (prices, failures), _ = self.fetch(
            ["AAPL", "NVDA"], self.quotes({"AAPL": 200.0})
        )
        self.assertEqual({f["ticker"] for f in failures}, {"NVDA"})
        self.assertEqual(set(prices), {"AAPL", "NVDA"}, "every requested ticker needs a key")
        self.assertIsNone(prices["NVDA"])

        (_p, failures), _ = self.fetch(
            ["AAPL", "NVDA"], self.quotes({"AAPL": 200.0, "NVDA": 500.0})
        )

        # AAPL is cached and so attempted nothing; NVDA succeeded. A stale record here would
        # light up data_quality.failures for a provider error that is an hour old.
        self.assertEqual(failures, [])

    def test_the_uncached_subset_goes_through_as_one_batch(self):
        # Per-ticker caching must not become a per-ticker *fetch*: TwelveData batches 8 symbols
        # per request, so three Yahoo misses belong in one call, not three.
        batch = {t: {"close": "10.0"} for t in ("AAPL", "MSFT", "NVDA")}
        (prices, _f), calls = self.fetch(
            ["AAPL", "MSFT", "NVDA"],
            self.quotes({}),
            twelvedata=lambda url, kw: response(payload=batch),
            key="fake-key",
        )

        twelvedata_calls = [url for url in calls if "twelvedata" in url]
        self.assertEqual(len(twelvedata_calls), 1, "the batch was split into one call per ticker")
        self.assertEqual(prices, {"AAPL": 10.0, "MSFT": 10.0, "NVDA": 10.0})


class TestTheTotalRecoversWithTheProvider(TempMappingCase):
    """KAN-54's headline symptom: the understated total must not outlive the blip.

    The market_service tests above prove the price is re-fetched; this proves what the user
    actually sees, because an unpriced ticker is coerced to 0 and silently contributes nothing
    to `total_market_value_gbp`.
    """

    MAPPINGS = {"Apple Inc": "AAPL", "Bogus Ltd": "BOGUS.L"}

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        temp_fx_store(self)

    def value(self, blip):
        def yahoo(url, kw):
            if "GBP" in url:  # the FX crosses, fetched as history rather than as a quote
                return response(payload=yahoo_history(closes=(1.29 if "GBPUSD" in url else 1.15,)))
            if blip and "AAPL" in url:
                raise requests.RequestException("connection reset")
            is_aapl = "AAPL" in url
            return response(payload=yahoo_quote(
                200.0 if is_aapl else 700.0, currency="USD" if is_aapl else "GBp"
            ))

        session, calls = session_stub(yahoo=yahoo)
        with patch.object(price_service, "_session", session), \
                patch.object(settings, "EODHD_API_TOKEN", None), \
                patch.object(settings, "TWELVEDATA_API_KEY", None):
            result = portfolio_engine.calculate_positions_from_df(trade_df())
        return result, [u for u in calls if "GBP" not in u]

    def test_the_next_request_restores_the_total_and_refetches_only_the_blip(self):
        blipped, _ = self.value(blip=True)
        self.assertEqual(blipped["data_quality"]["unpriced_tickers"], ["AAPL"])

        recovered, contacted = self.value(blip=False)

        self.assertEqual(recovered["data_quality"]["unpriced_tickers"], [])
        self.assertGreater(recovered["total_market_value_gbp"], blipped["total_market_value_gbp"])
        self.assertAlmostEqual(recovered["total_market_value_gbp"], 1606.39, places=2)
        self.assertEqual(
            [u for u in contacted if "AAPL" not in u], [],
            "BOGUS.L priced fine, so re-fetching it means the whole list was invalidated",
        )


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
