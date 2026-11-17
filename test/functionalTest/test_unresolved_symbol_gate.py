"""KAN-12: the unresolved-symbol gate, from upload through skip/confirm to the totals.

Exercised through the real `trades.upload_files` handler and the real engine, with only
prices, FX and the mapping file substituted.
"""
import asyncio
import io
import unittest

from starlette.datastructures import UploadFile

from backend.app.api.v1 import trades
from backend.app.schemas.portfolio import PortfolioSummary
from backend.app.services.ticker_service import (
    find_unresolved_symbols,
    load_ticker_mappings,
    save_ticker_mappings,
)
from test.support.portfolio import TRADE_CSV, TempMappingCase, run_engine, trade_df


class TestDetectionParity(TempMappingCase):
    """The reported unresolved rows must equal the rows the engine actually drops."""

    def test_reported_row_counts_equal_the_engine_exclusions(self):
        df = trade_df()
        unresolved = find_unresolved_symbols(df["Market"].tolist())
        result = run_engine(df)

        self.assertEqual(
            sum(item["row_count"] for item in unresolved), result["excluded_row_count"]
        )

    def test_repeats_are_collapsed_into_one_row_count(self):
        self.assertEqual(
            find_unresolved_symbols(["Bogus Ltd", "Bogus Ltd", "Apple Inc"]),
            [{"market_name": "Bogus Ltd", "row_count": 2}],
        )

    def test_results_are_ranked_by_blast_radius(self):
        names = ["Bogus Ltd"] + ["Noisy Plc"] * 3
        self.assertEqual(
            [item["market_name"] for item in find_unresolved_symbols(names)],
            ["Noisy Plc", "Bogus Ltd"],
        )

    def test_a_fully_mapped_history_reports_nothing(self):
        self.assertEqual(find_unresolved_symbols(["Apple Inc", "Apple Inc"]), [])


class TestBlankMappingDetection(TempMappingCase):
    """A name present in the JSON but mapped to null/'' is still unresolved.

    Streamlit's `~isin(keys())` predicate misses this case; detection has to use
    `resolve_ticker()` so the count matches the drop.
    """

    MAPPINGS = {"Apple Inc": "AAPL", "Bogus Ltd": None}

    def test_null_mapped_name_is_reported_and_dropped(self):
        df = trade_df()
        unresolved = find_unresolved_symbols(df["Market"].tolist())
        result = run_engine(df)

        self.assertEqual(unresolved, [{"market_name": "Bogus Ltd", "row_count": 2}])
        self.assertEqual(result["excluded_row_count"], 2)


class TestChainFollowingEndToEnd(TempMappingCase):
    """A chain-mapped name must survive detection AND the engine, under its final ticker."""

    MAPPINGS = {"Skillz Inc": "SKLZ", "SKLZ": "FIRY"}

    CSV = (
        "Market,Quantity,Cost/Proceeds,Charges,Commission,Currency,Date\n"
        "Skillz Inc,100,-250.0,0.0,0.0,USD,2024-01-02\n"
        "Skillz Inc,50,-100.0,0.0,0.0,USD,2024-01-03\n"
    )

    def test_chain_followed_name_is_not_reported_unresolved(self):
        self.assertEqual(find_unresolved_symbols(["Skillz Inc", "Skillz Inc"]), [])

    def test_chain_followed_rows_are_not_dropped(self):
        result = run_engine(trade_df(self.CSV))

        self.assertEqual(result["excluded_row_count"], 0)
        self.assertEqual([p["ticker"] for p in result["positions"]], ["FIRY"])
        self.assertEqual(result["positions"][0]["quantity"], 150.0)

    def test_upload_does_not_open_the_gate_for_a_chain_mapped_name(self):
        self.assertEqual(find_unresolved_symbols(trade_df(self.CSV)["Market"].tolist()), [])


class TestUploadOpensTheGate(TempMappingCase):
    """`POST /trades/upload` carries the payload Dashboard.tsx gates the valuation on."""

    USER = {"sub": "verify-ticker-service"}

    def tearDown(self):
        user_id = self.USER["sub"]
        for store in (
            trades._LAST_TRADE_DF,
            trades._LAST_TRADE_FILENAME,
            trades._LAST_TRANSACTION_DF,
            trades._LAST_TRANSACTION_FILENAME,
            trades._USER_MANUAL_UPLOAD,
        ):
            store.pop(user_id, None)

    def _upload(self, csv_text):
        upload = UploadFile(file=io.BytesIO(csv_text.encode()), filename="TradeHistory.csv")
        return asyncio.run(trades.upload_files(files=[upload], user=self.USER))

    def test_unmapped_name_comes_back_on_the_upload_response(self):
        results = self._upload(TRADE_CSV)

        self.assertEqual(
            results["unresolved_symbols"], [{"market_name": "Bogus Ltd", "row_count": 2}]
        )
        self.assertEqual(results["errors"], [])
        self.assertEqual(results["trade_files"], ["TradeHistory.csv"])

    def test_a_fully_mapped_upload_leaves_the_gate_shut(self):
        header, mapped_row = TRADE_CSV.splitlines()[:2]
        results = self._upload(f"{header}\n{mapped_row}\n")

        self.assertEqual(results["unresolved_symbols"], [])


class TestTotalsAcrossTheGate(TempMappingCase):
    """Skip warns on understated totals; confirming the mapping corrects them."""

    def test_skipping_excludes_the_rows_and_says_so(self):
        result = run_engine(trade_df())

        self.assertEqual(result["excluded_row_count"], 2)
        self.assertEqual(
            result["unresolved_symbols"], [{"market_name": "Bogus Ltd", "row_count": 2}]
        )
        self.assertEqual([p["ticker"] for p in result["positions"]], ["AAPL"])
        self.assertAlmostEqual(result["total_market_value_gbp"], 1600.0)
        self.assertAlmostEqual(result["total_invested_cash"], 1000.0)
        self.assertAlmostEqual(result["total_pnl_gbp"], 600.0)

    def test_confirming_the_mapping_corrects_every_total(self):
        save_ticker_mappings({"Bogus Ltd": "BOGUS.L"})
        result = run_engine(trade_df())

        self.assertEqual(result["excluded_row_count"], 0)
        self.assertEqual(result["unresolved_symbols"], [])
        self.assertEqual(
            sorted(p["ticker"] for p in result["positions"]), ["AAPL", "BOGUS.L"]
        )
        self.assertAlmostEqual(result["total_market_value_gbp"], 1656.0)
        self.assertAlmostEqual(result["total_invested_cash"], 1801.0)
        self.assertAlmostEqual(result["total_pnl_gbp"], -145.0)
        self.assertAlmostEqual(result["currency_allocation"]["usd_gbp"], 1600.0)
        self.assertAlmostEqual(result["currency_allocation"]["gbp"], 56.0)
        self.assertAlmostEqual(result["currency_allocation"]["total_gbp"], 1656.0)

    def test_the_dropped_rows_flip_the_sign_of_total_pnl(self):
        """Not a mere understatement: skipping turns a -£145 loss into a +£600 profit."""
        skipped = run_engine(trade_df())
        save_ticker_mappings({"Bogus Ltd": "BOGUS.L"})
        confirmed = run_engine(trade_df())

        self.assertGreater(skipped["total_pnl_gbp"], 0)
        self.assertLess(confirmed["total_pnl_gbp"], 0)

    def test_confirming_merges_rather_than_clobbers(self):
        """The modal PUTs only the new entries; the rest of the map must survive."""
        save_ticker_mappings({"Bogus Ltd": "BOGUS.L"})

        self.assertEqual(
            load_ticker_mappings(), {"Apple Inc": "AAPL", "Bogus Ltd": "BOGUS.L"}
        )

    def test_warning_fields_survive_the_response_schema(self):
        summary = PortfolioSummary(**run_engine(trade_df()))

        self.assertEqual(summary.excluded_row_count, 2)
        self.assertEqual(summary.unresolved_symbols[0].market_name, "Bogus Ltd")
        self.assertEqual(summary.unresolved_symbols[0].row_count, 2)


class TestEverythingUnresolved(TempMappingCase):
    """The empty-result path must carry the same warning fields as the normal path."""

    MAPPINGS = {}

    def test_empty_result_still_reports_the_exclusions(self):
        result = run_engine(trade_df())

        self.assertEqual(result["positions"], [])
        self.assertEqual(result["excluded_row_count"], 3)
        self.assertEqual(
            [item["market_name"] for item in result["unresolved_symbols"]],
            ["Bogus Ltd", "Apple Inc"],
        )
        self.assertEqual(result["total_market_value_gbp"], 0.0)


if __name__ == "__main__":
    unittest.main()
