"""KAN-56: the derived cash balance as `GET /trades/summary` actually returns it.

The derivation itself is covered in `test/unitTest/test_cash_balance_derivation.py`. What this
adds is the wiring: that the field is populated on *both* of the handler's return paths, that it
survives `PortfolioSummary`'s `response_model` rather than being silently dropped, and that
`total_invested_cash` -- which is cost basis, not cash -- is untouched beside it.

Driven through the real handler with only the mapping file, prices, FX and the `~/Downloads`
scan substituted, so nothing here reaches a provider or the developer's own statements.
"""
import unittest
from unittest.mock import patch

import pandas as pd

from backend.app.api.v1 import trades
from backend.app.schemas.portfolio import PortfolioSummary
from backend.app.services import portfolio_engine
from test.support.portfolio import (
    GBPEUR,
    GBPUSD,
    PRICES,
    TRANSACTION_BALANCE,
    TempMappingCase,
    trade_df,
    transaction_df,
)

USER = {"sub": "verify-cash-balance"}


class SummaryCase(TempMappingCase):
    """Calls the real `/summary` handler with every outside dependency stubbed."""

    def setUp(self):
        super().setUp()
        fx = ({"GBPUSD=X": pd.Series([GBPUSD]), "GBPEUR=X": pd.Series([GBPEUR])}, False)
        for target, new in (
            ("get_current_prices", lambda tickers: ({t: PRICES.get(t) for t in tickers}, [])),
            ("get_historical_fx", lambda start: fx),
        ):
            patcher = patch.object(portfolio_engine, target, new)
            patcher.start()
            self.addCleanup(patcher.stop)

        # Without this the handler autoloads whatever IG export happens to be in the developer's
        # ~/Downloads, which would both read real data and change the answer per machine.
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

    def load(self, trade=None, transaction=None):
        if trade is not None:
            trades._LAST_TRADE_DF[USER["sub"]] = trade
            trades._LAST_TRADE_FILENAME[USER["sub"]] = "TradeHistory.csv"
        if transaction is not None:
            trades._LAST_TRANSACTION_DF[USER["sub"]] = transaction
            trades._LAST_TRANSACTION_FILENAME[USER["sub"]] = "TransactionHistory.csv"
        return trades.get_portfolio_summary(user=USER)


class TestTheBalanceReachesTheResponse(SummaryCase):
    def setUp(self):
        super().setUp()
        self.res = self.load(trade=trade_df(), transaction=transaction_df())

    def test_the_handler_returns_the_derived_balance(self):
        self.assertEqual(self.res["cash_balance"]["balance_gbp"], TRANSACTION_BALANCE)

    def test_the_balance_survives_the_response_model(self):
        # The tile reads this off the serialised response; a field missing from the schema would
        # be dropped here with no error anywhere.
        summary = PortfolioSummary(**self.res)

        self.assertEqual(summary.cash_balance.balance_gbp, TRANSACTION_BALANCE)
        self.assertIsNone(summary.cash_balance.withheld_reason)

    def test_the_covered_window_survives_too(self):
        summary = PortfolioSummary(**self.res)

        self.assertEqual(summary.cash_balance.covered_from, "2019-04-01")
        self.assertEqual(summary.cash_balance.covered_to, "2019-04-05")

    def test_total_invested_cash_still_means_cost_basis(self):
        # Both are money in GBP, and the tile beside the new one reads this. Adding a cash
        # balance must not reinterpret it: this is the £1000 Apple Inc cost, not the ledger net.
        summary = PortfolioSummary(**self.res)

        self.assertIsInstance(summary.total_invested_cash, float)
        self.assertAlmostEqual(summary.total_invested_cash, 1000.0)
        self.assertNotEqual(summary.total_invested_cash, TRANSACTION_BALANCE)


class TestWithholdingReachesTheResponse(SummaryCase):
    def test_a_mid_life_statement_is_withheld_not_netted(self):
        summary = PortfolioSummary(
            **self.load(trade=trade_df(), transaction=transaction_df().iloc[1:])
        )

        self.assertIsNone(summary.cash_balance.balance_gbp)
        self.assertEqual(summary.cash_balance.withheld_reason, "partial_window")

    def test_no_statement_loaded_reports_no_ledger(self):
        # The trade history alone cannot yield a balance: it records positions, not cash.
        summary = PortfolioSummary(**self.load(trade=trade_df()))

        self.assertIsNone(summary.cash_balance.balance_gbp)
        self.assertEqual(summary.cash_balance.withheld_reason, "no_ledger")


class TestTheEmptyPortfolioPath(SummaryCase):
    """A statement with no trade history takes the handler's other return path.

    That path builds its dict by hand rather than from the engine, so the field has to be added
    to it separately -- and it is the one path where a balance is all there is to show.
    """

    def test_a_statement_without_trade_history_still_yields_a_balance(self):
        summary = PortfolioSummary(**self.load(transaction=transaction_df()))

        self.assertTrue(summary.missing_trade_history)
        self.assertEqual(summary.positions, [])
        self.assertEqual(summary.cash_balance.balance_gbp, TRANSACTION_BALANCE)

    def test_nothing_loaded_at_all_reports_no_ledger(self):
        summary = PortfolioSummary(**self.load())

        self.assertIsNone(summary.cash_balance.balance_gbp)
        self.assertEqual(summary.cash_balance.withheld_reason, "no_ledger")


if __name__ == "__main__":
    unittest.main()
