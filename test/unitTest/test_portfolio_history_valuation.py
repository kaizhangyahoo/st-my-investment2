"""Historical portfolio valuation: holdings reconstruction, currency conversion, cache merge.

Every provider is patched on the `history_service` bindings rather than on `market_service`,
which sidesteps the module-level `ttl_cache` singleton and keeps the suite offline.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import pandas as pd

from backend.app.core.config import settings
from backend.app.services import history_service
from test.support.portfolio import temp_fx_store

DATES = ["2024-01-02", "2024-01-03", "2024-01-04"]
GBPUSD, GBPEUR = 2.0, 1.25


def _history(closes, dates=DATES):
    return pd.DataFrame({"Date": pd.to_datetime(dates), "close": closes})


def _fx(dates=DATES):
    idx = pd.to_datetime(dates)
    return {
        "GBPUSD=X": pd.Series([GBPUSD] * len(idx), index=idx),
        "GBPEUR=X": pd.Series([GBPEUR] * len(idx), index=idx),
    }


class HistoryCase(unittest.TestCase):
    """Points the ticker map, the shared values file and the FX store at throwaway files."""

    MAPPINGS = {"Apple Inc": "AAPL", "Vodafone Group": "VOD.L", "Adidas AG": "ADS.DE"}
    PRICES = {}          # ticker -> (close series, quote currency)
    FX_FALLBACK = False
    SEED_CACHE = None    # initial contents of the shared values file
    # Real closes the FX store already holds. Whether the store is empty is how a degraded feed
    # is told apart from an approximated one, so a seed is needed to exercise the former.
    SEED_FX = None

    def setUp(self):
        temp_fx_store(self, seed=self.SEED_FX)
        self.tmpdir = tempfile.mkdtemp(prefix="verify_history_")
        self.map_path = os.path.join(self.tmpdir, "ticker_map.json")
        self.values_path = os.path.join(self.tmpdir, "user_portfolio_values.json")
        with open(self.map_path, "w") as f:
            json.dump(self.MAPPINGS, f)
        if self.SEED_CACHE is not None:
            with open(self.values_path, "w") as f:
                json.dump(self.SEED_CACHE, f)

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(settings, "TICKER_MAP_FILE", self.map_path))
        from backend.app.services.ticker_service import load_ticker_mappings
        load_ticker_mappings.clear()
        self.addCleanup(load_ticker_mappings.clear)
        stack.enter_context(patch.object(settings, "PORTFOLIO_VALUES_FILE", self.values_path))
        self.assertEqual(settings.PORTFOLIO_VALUES_FILE, self.values_path)

        prices = self.PRICES
        stack.enter_context(patch.object(
            history_service, "get_price_history",
            lambda t, s: prices.get(t, (pd.DataFrame(columns=["Date", "close"]), None)),
        ))
        stack.enter_context(patch.object(
            history_service, "get_historical_fx", lambda s: (_fx(), self.FX_FALLBACK)
        ))

    def run_history(self, csv_text, key="ig:u1", force_recompute=False):
        df = pd.read_csv(io.StringIO(csv_text))
        return history_service.compute_history(df, key, force_recompute=force_recompute)

    def values(self, result):
        return {p["date"]: round(p["value"], 6) for p in result["points"]}

    def stored(self):
        with open(self.values_path) as f:
            return json.load(f)


class TestHoldingsReconstruction(HistoryCase):
    PRICES = {"AAPL": (_history([100.0, 110.0, 120.0]), "USD")}

    def test_quantity_accumulates_as_of_each_date(self):
        # Buy 10 on the 2nd, buy 5 more on the 3rd, sell all 15 on the 4th.
        res = self.run_history(
            "Market,Quantity,Date\n"
            "Apple Inc,10,2024-01-02\n"
            "Apple Inc,5,2024-01-03\n"
            "Apple Inc,-15,2024-01-04\n"
        )
        # USD closes convert at GBPUSD=2.0: 10x100/2=500, 15x110/2=825, flat after the exit.
        self.assertEqual(self.values(res), {
            "2024-01-02": 500.0,
            "2024-01-03": 825.0,
            "2024-01-04": 0.0,
        })

    def test_trade_counts_on_its_own_day(self):
        res = self.run_history("Market,Quantity,Date\nApple Inc,10,2024-01-03\n")
        series = self.values(res)
        self.assertEqual(series["2024-01-03"], 550.0)
        self.assertNotIn("2024-01-02", series, "a date before the first trade must not be valued")


class TestCurrencyConversion(HistoryCase):
    PRICES = {
        "VOD.L": (_history([200.0, 200.0, 200.0]), "GBp"),
        "AAPL": (_history([100.0, 100.0, 100.0]), "USD"),
        "ADS.DE": (_history([50.0, 50.0, 50.0]), "EUR"),
    }

    def test_pence_quotes_are_divided_by_one_hundred(self):
        res = self.run_history("Market,Quantity,Date\nVodafone Group,10,2024-01-02\n")
        # 10 shares x 200 GBp = 2000 pence = £20.00
        self.assertEqual(self.values(res)["2024-01-02"], 20.0)

    def test_pound_quoted_lse_instrument_is_not_divided(self):
        """The legacy divide-by-100 keyed off the CSV Currency column, so it wrongly scaled
        LSE instruments that quote in pounds. Yahoo reports GBP for those, not GBp."""
        with patch.dict(self.PRICES, {"VOD.L": (_history([2.0, 2.0, 2.0]), "GBP")}, clear=False):
            res = self.run_history("Market,Quantity,Date\nVodafone Group,10,2024-01-02\n")
        self.assertEqual(self.values(res)["2024-01-02"], 20.0)

    def test_usd_and_eur_convert_at_their_own_cross(self):
        res = self.run_history(
            "Market,Quantity,Date\n"
            "Apple Inc,10,2024-01-02\n"
            "Adidas AG,4,2024-01-02\n"
        )
        # AAPL 10x100/2.0 = 500; ADS 4x50/1.25 = 160
        self.assertEqual(self.values(res)["2024-01-02"], 660.0)


class TestIncompleteDataInvalidatesDate(HistoryCase):
    PRICES = {
        "AAPL": (_history([100.0, 100.0, 100.0]), "USD"),
        # Quoted in a currency we hold no cross for.
        "ADS.DE": (_history([50.0, 50.0, 50.0]), "CHF"),
    }

    def test_unconvertible_currency_skips_the_date_instead_of_contributing_zero(self):
        """Legacy seeded GBP_Value with 0.0 and filled only USD/EUR/GBP, so an unexpected
        currency silently understated the total rather than flagging it."""
        res = self.run_history(
            "Market,Quantity,Date\n"
            "Apple Inc,10,2024-01-02\n"
            "Adidas AG,4,2024-01-02\n"
        )
        self.assertEqual(res["points"], [], "no date should be valued while a holding is unconvertible")
        quality = res["data_quality"]
        self.assertTrue(quality["degraded"])
        self.assertEqual(quality["unconvertible"], [{"ticker": "ADS.DE", "currency": "CHF"}])
        self.assertEqual(quality["skipped_dates"], 3)

    def test_missing_close_for_a_held_position_skips_only_that_date(self):
        partial = _history([100.0, 100.0], dates=["2024-01-02", "2024-01-04"])
        with patch.dict(self.PRICES, {"ADS.DE": (partial, "EUR")}, clear=False):
            res = self.run_history(
                "Market,Quantity,Date\n"
                "Apple Inc,10,2024-01-02\n"
                "Adidas AG,4,2024-01-02\n"
            )
        series = self.values(res)
        self.assertNotIn("2024-01-03", series, "ADS.DE has no close on the 3rd")
        self.assertEqual(series["2024-01-02"], 820.0)  # 500 + 4x100/1.25
        self.assertEqual(res["data_quality"]["skipped_dates"], 1)

    def test_unpriced_ticker_is_reported(self):
        with patch.dict(self.PRICES, {"AAPL": (pd.DataFrame(columns=["Date", "close"]), None)}):
            res = self.run_history("Market,Quantity,Date\nApple Inc,10,2024-01-02\n")
        self.assertEqual(res["data_quality"]["unpriced_tickers"], ["AAPL"])
        self.assertTrue(res["data_quality"]["degraded"])


class TestFxUnbackedDatesAreWithheld(HistoryCase):
    """KAN-55: a date is persisted only if a real FX rate covers it.

    `_fx_frames` carries the last known rate across the end of the series, which is the right
    answer for a market holiday and the wrong one to save: the shared values file holds a bare
    float with nowhere to record that it was approximated, and `compute_history` never revisits a
    date already in it. The estimate would be permanent -- and, because the old `fx_fallback`
    described only the work this request did, reported as clean on every later read.
    """

    PRICES = {
        "AAPL": (_history([100.0, 100.0, 100.0]), "USD"),
        "VOD.L": (_history([200.0, 200.0, 200.0]), "GBp"),
    }
    # The feed stops a day short of the closes: real rates through the 3rd, nothing for the 4th.
    BACKED = DATES[:2]
    SEED_FX = {
        "GBPUSD=X": {d: GBPUSD for d in BACKED},
        "GBPEUR=X": {d: GBPEUR for d in BACKED},
    }
    TRADES = "Market,Quantity,Date\nApple Inc,10,2024-01-02\n"

    def run_truncated(self, trades=None):
        with patch.object(
            history_service, "get_historical_fx", lambda s: (_fx(self.BACKED), False)
        ):
            return self.run_history(trades or self.TRADES)

    def test_the_date_past_the_last_real_rate_is_not_valued(self):
        self.assertEqual(sorted(self.values(self.run_truncated())), self.BACKED)

    def test_it_is_withheld_rather_than_stored_as_an_estimate(self):
        self.run_truncated()
        self.assertEqual(sorted(self.stored()["ig:u1"]), self.BACKED)

    def test_the_withheld_dates_are_counted_and_announced(self):
        quality = self.run_truncated()["data_quality"]
        self.assertEqual(quality["fx_unbacked_dates"], 1)
        self.assertEqual(quality["skipped_dates"], 0, "the close was there; the rate was not")
        self.assertTrue(quality["fx_fallback"])
        self.assertTrue(quality["degraded"])

    def test_a_gbp_only_holding_needs_no_rate_and_is_valued_in_full(self):
        res = self.run_truncated("Market,Quantity,Date\nVodafone Group,10,2024-01-02\n")
        self.assertEqual(sorted(self.values(res)), DATES)
        self.assertEqual(res["data_quality"]["fx_unbacked_dates"], 0)
        self.assertFalse(res["data_quality"]["fx_fallback"])

    def test_the_date_is_recomputed_once_a_real_rate_exists(self):
        # This is what withholding buys: a stored date is never revisited, so a value written
        # today at a guessed rate could never be corrected.
        self.run_truncated()
        later = self.run_history(self.TRADES)
        self.assertEqual(sorted(self.values(later)), DATES)
        self.assertEqual(later["data_quality"]["fx_unbacked_dates"], 0)
        self.assertFalse(later["data_quality"]["fx_fallback"])

    def test_approximated_rates_back_no_date_at_all(self):
        # An empty store is what tells the hardcoded constants apart from real-but-stale rates:
        # the constants' index runs to today and backs nothing on it.
        temp_fx_store(self)
        with patch.object(history_service, "get_historical_fx", lambda s: (_fx(), True)):
            res = self.run_history(self.TRADES)
        self.assertEqual(res["points"], [])
        self.assertEqual(res["data_quality"]["fx_unbacked_dates"], len(DATES))


class TestSharedCacheFile(HistoryCase):
    PRICES = {"AAPL": (_history([100.0, 110.0, 120.0]), "USD")}
    SEED_CACHE = {"QX2B3": {"2019-04-30": 1234.5}}
    TRADES = "Market,Quantity,Date\nApple Inc,10,2024-01-02\n"

    def test_write_preserves_the_legacy_trading212_keys(self):
        self.run_history(self.TRADES)
        stored = self.stored()
        self.assertEqual(stored["QX2B3"], {"2019-04-30": 1234.5})
        self.assertEqual(sorted(stored["ig:u1"]), DATES)

    def test_only_uncached_dates_are_recomputed(self):
        self.run_history(self.TRADES)
        calls = []

        def counting_fx(start):
            calls.append(start)
            return _fx(), False

        with patch.object(history_service, "get_historical_fx", counting_fx):
            again = self.run_history(self.TRADES)
        self.assertEqual(calls, [], "a fully cached series must not recompute any date")
        self.assertEqual(sorted(self.values(again)), DATES)

    def test_force_recompute_drops_values_that_are_no_longer_valuable(self):
        self.run_history(self.TRADES)
        self.assertIn("2024-01-04", self.stored()["ig:u1"])

        shrunk = _history([100.0], dates=["2024-01-02"])
        with patch.dict(self.PRICES, {"AAPL": (shrunk, "USD")}, clear=False):
            self.run_history(self.TRADES, force_recompute=True)

        remaining = self.stored()["ig:u1"]
        self.assertEqual(sorted(remaining), ["2024-01-02"])
        self.assertEqual(self.stored()["QX2B3"], {"2019-04-30": 1234.5})

    def test_legacy_series_is_readable_verbatim(self):
        self.assertEqual(
            history_service.read_cached_series("QX2B3"),
            [{"date": "2019-04-30", "value": 1234.5}],
        )

    def test_fx_fallback_marks_the_series_degraded(self):
        with patch.object(history_service, "get_historical_fx", lambda s: (_fx(), True)):
            res = self.run_history(self.TRADES)
        self.assertTrue(res["data_quality"]["fx_fallback"])
        self.assertTrue(res["data_quality"]["degraded"])


class TestDefaultAccount(HistoryCase):
    """KAN-46: no aggregate and no hard-coded id, so the landing view is the richest series."""

    def test_the_account_with_the_most_values_wins(self):
        history_service._merge_and_write("QX2B3", {"2019-05-01": 1.0, "2019-05-02": 2.0})
        history_service._merge_and_write("QRPOL", {"2019-05-01": 9.0})
        self.assertEqual(history_service.default_account(), "QX2B3")

    def test_a_tie_breaks_on_name_so_the_landing_view_is_stable(self):
        history_service._merge_and_write("BBB", {"2019-05-01": 1.0})
        history_service._merge_and_write("AAA", {"2019-05-01": 1.0})
        self.assertEqual(history_service.default_account(), "AAA")

    def test_an_empty_store_has_no_default(self):
        self.assertFalse(os.path.exists(settings.PORTFOLIO_VALUES_FILE))
        self.assertIsNone(history_service.default_account())


class TestIsBehind(unittest.TestCase):
    """Only a tail counts as fillable. Interior misses in the real file are market holidays."""

    @staticmethod
    def series(*dates):
        return [{"date": d, "value": 1.0} for d in dates]

    def test_a_series_ending_today_is_not_behind(self):
        self.assertFalse(history_service.is_behind(self.series("2026-11-20"), today="2026-11-20"))

    def test_a_series_stopping_before_today_is_behind(self):
        self.assertTrue(history_service.is_behind(self.series("2026-11-18"), today="2026-11-20"))

    def test_an_interior_holiday_is_not_a_gap(self):
        # 2026-01-01 missing between two stored days must not offer a recompute.
        points = self.series("2025-12-31", "2026-01-02")
        self.assertFalse(history_service.is_behind(points, today="2026-01-02"))

    def test_a_weekend_does_not_make_friday_stale(self):
        # Friday 2026-11-20 stored, "today" Sunday 2026-11-22: no business day was missed.
        self.assertFalse(history_service.is_behind(self.series("2026-11-20"), today="2026-11-22"))

    def test_an_empty_series_is_behind_so_a_new_user_can_compute_one(self):
        self.assertTrue(history_service.is_behind([], today="2026-11-20"))


if __name__ == "__main__":
    unittest.main()
