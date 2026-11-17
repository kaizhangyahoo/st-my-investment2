"""KAN-18 item 5 / KAN-12: the response fields that tell the UI the figures may be wrong.

These are additive and optional by design -- an older payload without them must still
validate, or the migration breaks every client at once.
"""
import unittest

from backend.app.schemas.portfolio import DataQuality, PortfolioSummary
from backend.app.services import portfolio_engine


class TestDataQualityShape(unittest.TestCase):
    def test_empty_data_quality_is_the_all_clear_shape(self):
        self.assertEqual(
            portfolio_engine.empty_data_quality(),
            {"degraded": False, "fx_fallback": False, "unpriced_tickers": [], "failures": []},
        )

    def test_empty_data_quality_validates_against_the_schema(self):
        dq = DataQuality(**portfolio_engine.empty_data_quality())
        self.assertFalse(dq.degraded)
        self.assertEqual(dq.unpriced_tickers, [])

    def test_data_quality_stays_optional_on_the_summary(self):
        self.assertFalse(PortfolioSummary.model_fields["data_quality"].is_required())


class TestExclusionWarningShape(unittest.TestCase):
    def test_warning_fields_default_to_quiet_when_omitted(self):
        summary = PortfolioSummary(
            total_market_value_gbp=0.0,
            total_invested_cash=0.0,
            total_pnl_gbp=0.0,
            currency_allocation={"usd_gbp": 0.0, "eur_gbp": 0.0, "gbp": 0.0, "total_gbp": 0.0},
            positions=[],
        )

        self.assertEqual(summary.unresolved_symbols, [])
        self.assertEqual(summary.excluded_row_count, 0)


if __name__ == "__main__":
    unittest.main()
