"""KAN-18 item 5: the engine turns raw provider outcomes into the flags the sidebar reads.

Ticker resolution is patched out here on purpose -- these tests are about price and FX
outcomes, so the mapping is supplied as a dict rather than a file. The resolution path
itself is covered in test_unresolved_symbol_gate.py.
"""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import pandas as pd

from backend.app.services import portfolio_engine


class TestEngineDataQuality(unittest.TestCase):
    @staticmethod
    def _trade_df():
        return pd.DataFrame([
            {"Market": "Apple Inc", "Quantity": 10, "Cost/Proceeds": -1000.0, "Charges": 0.0,
             "Commission": 0.0, "Currency": "USD", "Date": pd.Timestamp("2024-01-02")},
            {"Market": "PayPoint", "Quantity": 5, "Cost/Proceeds": -40.0, "Charges": 0.0,
             "Commission": 0.0, "Currency": "GBP", "Date": pd.Timestamp("2024-01-03")},
        ])

    def _run(self, prices, failures=(), fx_fallback=False):
        tickers = {"Apple Inc": "AAPL", "PayPoint": "PAY.L"}
        fx = (
            {"GBPUSD=X": pd.Series([1.29]), "GBPEUR=X": pd.Series([1.15])},
            fx_fallback,
        )
        with ExitStack() as stack:
            for target, new in (
                ("load_ticker_mappings", lambda: {}),
                ("resolve_ticker", lambda name, mapping: tickers.get(name)),
                ("find_unresolved_symbols", lambda names: []),
                ("get_current_prices", lambda t: (prices, list(failures))),
                ("get_historical_fx", lambda start: fx),
            ):
                stack.enter_context(patch.object(portfolio_engine, target, new))
            return portfolio_engine.calculate_positions_from_df(self._trade_df())

    def test_clean_run_reports_no_problems(self):
        dq = self._run({"AAPL": 200.0, "PAY.L": 7.72})["data_quality"]
        self.assertEqual(
            dq, {"degraded": False, "fx_fallback": False, "unpriced_tickers": [], "failures": []}
        )

    def test_failure_on_a_priced_ticker_does_not_degrade(self):
        """A recorded failure plus a working fallback is the PARTIAL case, not DEGRADED.

        Dashboard.tsx deriveFeedStatus maps `degraded=False` + non-empty failures to
        'partial', so this combination is what drives the amber sidebar state.
        """
        failure = {"ticker": "PAY.L", "provider": "yahoo", "reason": "no regularMarketPrice"}
        dq = self._run({"AAPL": 200.0, "PAY.L": 7.72}, failures=[failure])["data_quality"]

        self.assertFalse(dq["degraded"])
        self.assertEqual(dq["unpriced_tickers"], [])
        self.assertEqual(dq["failures"], [failure])

    def test_unpriced_ticker_degrades(self):
        dq = self._run({"AAPL": 200.0, "PAY.L": None})["data_quality"]
        self.assertTrue(dq["degraded"])
        self.assertEqual(dq["unpriced_tickers"], ["PAY.L"])

    def test_fx_fallback_degrades_and_is_flagged(self):
        dq = self._run({"AAPL": 200.0, "PAY.L": 7.72}, fx_fallback=True)["data_quality"]
        self.assertTrue(dq["fx_fallback"])
        self.assertTrue(dq["degraded"])


if __name__ == "__main__":
    unittest.main()
