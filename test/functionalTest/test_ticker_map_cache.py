"""KAN-68: Caching load_ticker_mappings and parse count constraints on /trades/summary."""
import json
import os
import unittest
from unittest.mock import patch

import pandas as pd

from backend.app.api.v1 import tickers, trades
from backend.app.schemas.portfolio import UpdateMappingsRequest
from backend.app.services.ticker_service import (
    TICKER_MAP_TTL,
    load_ticker_mappings,
    save_ticker_mappings,
)
from test.support.portfolio import (
    GBPEUR,
    GBPUSD,
    PRICES,
    TempMappingCase,
    trade_df,
    transaction_df,
)

USER = {"sub": "verify-ticker-map-cache"}


class TestTradesSummaryTickerMapCache(TempMappingCase):
    MAPPINGS = {"Apple Inc": "AAPL", "Bogus Ltd": "BOGUS.L"}

    def setUp(self):
        super().setUp()
        from backend.app.services import portfolio_engine

        fx = ({"GBPUSD=X": pd.Series([GBPUSD]), "GBPEUR=X": pd.Series([GBPEUR])}, False)
        for target, new in (
            ("get_current_prices", lambda tickers: ({t: PRICES.get(t) for t in tickers}, [])),
            ("get_historical_fx", lambda start: fx),
        ):
            patcher = patch.object(portfolio_engine, target, new)
            patcher.start()
            self.addCleanup(patcher.stop)

        no_downloads = patch.object(trades, "find_latest_download_files", lambda: (None, None))
        no_downloads.start()
        self.addCleanup(no_downloads.stop)

        self.addCleanup(self._forget_user)

    def _forget_user(self):
        for store in (
            trades._LAST_TRADE_DF,
            trades._LAST_TRADE_FILENAME,
            trades._LAST_TRANSACTION_DF,
            trades._LAST_TRANSACTION_FILENAME,
            trades._USER_MANUAL_UPLOAD,
        ):
            store.pop(USER["sub"], None)

    def _load_data(self):
        trades._LAST_TRADE_DF[USER["sub"]] = trade_df()
        trades._LAST_TRADE_FILENAME[USER["sub"]] = "TradeHistory.csv"
        trades._LAST_TRANSACTION_DF[USER["sub"]] = transaction_df()
        trades._LAST_TRANSACTION_FILENAME[USER["sub"]] = "TransactionHistory.csv"

    def test_one_trades_summary_request_parses_mapping_file_at_most_once(self):
        """A single /trades/summary request parses company_name_to_ticker.json at most once (KAN-68)."""
        self._load_data()

        parse_count = 0
        real_json_load = json.load

        def counting_load(fp, *args, **kwargs):
            nonlocal parse_count
            parse_count += 1
            return real_json_load(fp, *args, **kwargs)

        with patch("json.load", side_effect=counting_load):
            res = trades.get_portfolio_summary(user=USER)
            self.assertEqual(parse_count, 1, "Cold request must parse ticker mapping file at most once")
            self.assertGreater(len(res["positions"]), 0)

        # A second request against warm cache should perform 0 parses
        with patch("json.load", side_effect=counting_load):
            parse_count = 0
            trades.get_portfolio_summary(user=USER)
            self.assertEqual(parse_count, 0, "Warm request must not re-parse the mapping file")

    def test_save_ticker_mappings_invalidates_cache(self):
        """Saving via save_ticker_mappings invalidates cache so updates are immediately visible."""
        # Warm the cache
        self.assertEqual(load_ticker_mappings()["Apple Inc"], "AAPL")
        self.assertNotIn("New Company", load_ticker_mappings())

        # Save new mapping
        save_ticker_mappings({"New Company": "NEW"})

        # Must be immediately visible without process restart
        updated = load_ticker_mappings()
        self.assertEqual(updated.get("New Company"), "NEW")
        self.assertEqual(updated.get("Apple Inc"), "AAPL")

    def test_tickers_put_endpoint_invalidates_cache(self):
        """PUT /tickers/mappings invalidates the cache through the write path."""
        # Warm the cache
        self.assertNotIn("API Added", load_ticker_mappings())

        payload = UpdateMappingsRequest(mappings={"API Added": "API"}, replace=False)
        tickers.update_mappings(payload=payload, user=USER)

        self.assertEqual(load_ticker_mappings().get("API Added"), "API")

    def test_disk_edit_becomes_visible_after_ttl_or_invalidation(self):
        """Direct file edits on disk are visible once invalidated or after TTL."""
        # Warm cache
        self.assertEqual(load_ticker_mappings()["Apple Inc"], "AAPL")

        # Simulate direct edit to disk file (outside application)
        with open(self.map_path, "w") as f:
            json.dump({**self.MAPPINGS, "Direct Disk": "DISK"}, f)

        # Before invalidation, cached value is served
        self.assertNotIn("Direct Disk", load_ticker_mappings())

        # After invalidation (simulating TTL expiry)
        load_ticker_mappings.clear()
        self.assertEqual(load_ticker_mappings()["Direct Disk"], "DISK")

    def test_ttl_constant_is_documented_and_bounded(self):
        """TTL chosen is 300 seconds (5 minutes) and documented."""
        self.assertEqual(TICKER_MAP_TTL, 300)


if __name__ == "__main__":
    unittest.main()
