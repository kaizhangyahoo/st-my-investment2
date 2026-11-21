"""The on-disk FX store and the one fetcher that fills it (KAN-55).

Every test redirects `settings.FX_HISTORY_FILE`: the module's whole job is to write a file, and
the default path is the repo's own `fx_history.json`.

`get_historical_fx` is covered here too, because the store's contract is only observable through
it -- what gets written, what is served when the provider is gone, and how much is re-fetched.
Yahoo is stubbed at `market_service.fetch_yahoo_history`, so nothing reaches a provider.
"""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests

from backend.app.core.cache import cache
from backend.app.core.config import settings
from backend.app.services import fx_store, market_service
from test.support.portfolio import fx_frame, temp_fx_store

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

SEED = {
    "GBPUSD=X": {"2024-02-29": 1.27, "2024-03-01": 1.29},
    "GBPEUR=X": {"2024-02-29": 1.16, "2024-03-01": 1.17},
}


class StoreCase(unittest.TestCase):
    SEED_FX = None

    def setUp(self):
        self.store = temp_fx_store(self, seed=self.SEED_FX)

    def write(self, text):
        with open(self.store, "w") as f:
            f.write(text)

    def stored(self):
        with open(self.store) as f:
            return json.load(f)


class TestReadingTheStore(StoreCase):
    def test_a_missing_file_is_an_empty_store_not_an_error(self):
        self.assertEqual(fx_store.read_rates(), {})

    def test_unreadable_contents_degrade_to_an_empty_store(self):
        # A half-written or hand-edited file must not take the dashboard down with it.
        self.write("{not json")
        self.assertEqual(fx_store.read_rates(), {})

    def test_a_malformed_entry_does_not_cost_us_the_rest_of_the_history(self):
        self.write(json.dumps({
            "GBPUSD=X": {
                "2024-03-01": 1.29,
                "01/03/2024": 1.30,   # not an ISO date
                "2024-03-04": "n/a",  # not a number
                "2024-03-05": 0,      # a zero rate would divide a valuation into nonsense
                "2024-03-06": -1.2,
            },
            "GBPEUR=X": "not a series",
        }))
        self.assertEqual(fx_store.read_rates(), {"GBPUSD=X": {"2024-03-01": 1.29}})


class TestMergingRates(StoreCase):
    SEED_FX = SEED

    def test_new_dates_are_added_without_dropping_the_old_ones(self):
        fx_store.merge_rates({"GBPUSD=X": {"2024-03-04": 1.31}})
        self.assertEqual(
            self.stored()["GBPUSD=X"],
            {"2024-02-29": 1.27, "2024-03-01": 1.29, "2024-03-04": 1.31},
        )
        self.assertEqual(self.stored()["GBPEUR=X"], SEED["GBPEUR=X"])

    def test_a_refetched_date_is_corrected_rather_than_kept(self):
        fx_store.merge_rates({"GBPUSD=X": {"2024-03-01": 1.30}})
        self.assertEqual(self.stored()["GBPUSD=X"]["2024-03-01"], 1.30)

    def test_todays_rate_is_served_but_never_settled(self):
        # Yahoo's last row is the in-progress bar. Storing it would hand tomorrow's caller an
        # intraday snapshot as though it were the close.
        fx_store.merge_rates({"GBPUSD=X": {YESTERDAY: 1.32, TODAY: 1.33}})
        stored = self.stored()["GBPUSD=X"]
        self.assertIn(YESTERDAY, stored)
        self.assertNotIn(TODAY, stored)

    def test_nothing_worth_storing_leaves_the_file_alone(self):
        before = os.stat(self.store).st_mtime_ns
        fx_store.merge_rates({"GBPUSD=X": {TODAY: 1.33}})
        self.assertEqual(os.stat(self.store).st_mtime_ns, before)

    def test_the_write_leaves_no_temporary_file_behind(self):
        fx_store.merge_rates({"GBPUSD=X": {"2024-03-04": 1.31}})
        directory = os.path.dirname(self.store)
        self.assertEqual(
            [name for name in os.listdir(directory) if name != "fx_history.json"], []
        )


class TestCoverage(StoreCase):
    SEED_FX = SEED

    def test_coverage_ends_where_the_shorter_pair_does(self):
        # A valuation can hold both USD and EUR, so a date is only sound if every cross is real.
        fx_store.merge_rates({"GBPUSD=X": {"2024-03-04": 1.31}})
        self.assertEqual(fx_store.covered_through(), "2024-03-01")

    def test_a_pair_with_no_history_means_no_coverage(self):
        self.write(json.dumps({"GBPUSD=X": SEED["GBPUSD=X"]}))
        self.assertIsNone(fx_store.covered_through())

    def test_an_empty_store_covers_nothing(self):
        self.write("{}")
        self.assertIsNone(fx_store.covered_through())


class TestHowMuchIsRefetched(StoreCase):
    SEED_FX = SEED

    def test_an_empty_store_fetches_the_whole_range(self):
        self.write("{}")
        self.assertEqual(fx_store.fetch_from("2024-01-01"), "2024-01-01")

    def test_a_populated_store_fetches_only_the_tail(self):
        # Overlapping the stored history by a week keeps "the provider returned nothing" a
        # reliable failure signal: asking only for the day after the last close would come back
        # empty every Saturday.
        self.assertEqual(fx_store.fetch_from("2024-03-01"), "2024-02-23")

    def test_history_older_than_the_store_is_fetched_in_full(self):
        # Closes cannot be forward-filled backwards, so an earlier start really does need asking.
        self.assertEqual(fx_store.fetch_from("2024-01-01"), "2024-01-01")

    def test_a_later_start_still_continues_from_the_store(self):
        # Fetching only from the caller's start would leave a hole in the middle of the store,
        # which is invisible afterwards -- `_fx_frames` fills across it exactly as it fills a
        # weekend.
        self.assertEqual(fx_store.fetch_from("2024-06-01"), "2024-02-23")


class TestWhatTheFetcherStores(StoreCase):
    """`get_historical_fx` is the store's only writer."""

    SEED_FX = None

    def setUp(self):
        super().setUp()
        cache.clear()  # get_historical_fx is @ttl_cache'd on a shared module-level singleton
        self.addCleanup(cache.clear)
        self.asked = []

    def fetch(self, yahoo, start_date="2024-03-01"):
        """One request, cold. The TTL is what `test_provider_resilience` is for; here a second
        call has to reach the store, which a cache hit on the same `start_date` would skip."""
        cache.clear()

        def record(symbol, start, interval="1d"):
            self.asked.append(start)
            return yahoo(symbol, start)

        with patch.object(market_service, "fetch_yahoo_history", record):
            return market_service.get_historical_fx(start_date)

    @staticmethod
    def rates(dates=("2024-03-01",)):
        return lambda symbol, _start: fx_frame(
            1.29 if symbol == "GBPUSD=X" else 1.17, dates=dates
        )

    @staticmethod
    def unreachable(*_args, **_kwargs):
        raise requests.RequestException("yahoo unreachable")

    def test_real_closes_are_persisted_for_the_next_request(self):
        self.fetch(self.rates())
        self.assertEqual(self.stored(), {
            "GBPUSD=X": {"2024-03-01": 1.29},
            "GBPEUR=X": {"2024-03-01": 1.17},
        })

    def test_todays_close_is_returned_without_being_stored(self):
        fx, fallback = self.fetch(self.rates(dates=(YESTERDAY, TODAY)))
        self.assertFalse(fallback)
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.29)
        self.assertEqual(list(self.stored()["GBPUSD=X"]), [YESTERDAY])

    def test_a_stored_history_shortens_the_next_fetch(self):
        self.fetch(self.rates())
        self.asked.clear()
        self.fetch(self.rates(), start_date="2024-03-01")
        self.assertEqual(self.asked, ["2024-02-23", "2024-02-23"])

    def test_an_outage_leaves_the_stored_history_untouched(self):
        self.fetch(self.rates())
        before = self.stored()
        _fx, fallback = self.fetch(self.unreachable)
        self.assertTrue(fallback)
        self.assertEqual(self.stored(), before)

    def test_the_last_real_rate_is_served_instead_of_the_constants(self):
        self.fetch(self.rates())
        fx, fallback = self.fetch(self.unreachable)
        self.assertTrue(fallback, "the feed is degraded even though the rates are real")
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), 1.29)
        self.assertAlmostEqual(float(fx["GBPEUR=X"].iloc[-1]), 1.17)

    def test_the_constants_are_reached_only_with_nothing_to_fall_back_on(self):
        fx, fallback = self.fetch(self.unreachable)
        self.assertTrue(fallback)
        self.assertAlmostEqual(float(fx["GBPUSD=X"].iloc[-1]), market_service._FALLBACK_GBPUSD)
        self.assertFalse(os.path.exists(settings.FX_HISTORY_FILE))


if __name__ == "__main__":
    unittest.main()
