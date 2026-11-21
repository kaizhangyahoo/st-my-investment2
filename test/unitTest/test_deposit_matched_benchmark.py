"""KAN-58: the benchmark line fed by the account's own deposits.

The comparison line used to be raw index closes scaled onto the curve's first visible value. One
factor over the whole series means "a single lump sum invested on day one", so on the reference
account it compared GBP 94,633 of real deposits against GBP 835 of index -- and because the factor
was recomputed per window, every timeframe silently measured a different thing.

These tests cover the two halves of the replacement: picking the deposits out of the statement
(`external_cashflows`) and turning them into units (`deposit_matched_series`). Both are offline by
construction -- frames go in directly, no provider is involved.
"""
import unittest

import pandas as pd

from backend.app.services.benchmark_service import deposit_matched_series
from backend.app.services.portfolio_engine import external_cashflows
from test.support.portfolio import transaction_df

# A deposit, then a doubling. Chosen so every expected value below is checkable by eye.
CLOSES = pd.DataFrame(
    {"Date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "close": [100.0, 200.0]}
)


def closes(dates, values):
    return pd.DataFrame({"Date": pd.to_datetime(list(dates)), "close": list(values)})


def ledger(drop=(), extra_rows=None, **overrides):
    """The shared sample statement, optionally with columns dropped, cells replaced or rows added."""
    df = transaction_df()
    for column, values in overrides.items():
        df[column] = values
    if extra_rows is not None:
        df = pd.concat([pd.DataFrame(extra_rows), df], ignore_index=True)
    return df.drop(columns=list(drop))


class TestOnlyExternalMoneyCounts(unittest.TestCase):
    """A benchmark fed by anything other than deposits is buying the index with its own returns."""

    def test_the_deposit_is_picked_out_and_the_internal_flows_are_not(self):
        result = external_cashflows(ledger())
        # The sample statement holds one Cash In plus a consideration, a dividend, a commission
        # and a sale. Only the first is new money.
        self.assertEqual(
            result["cashflows"], [{"date": "2019-04-01", "amount_gbp": 5000.0}]
        )
        self.assertEqual(result["total_gbp"], 5000.0)

    def test_a_dividend_is_not_treated_as_a_contribution(self):
        # Reinvesting dividends into the benchmark would credit it with money the index already
        # reflects in its own total-return behaviour, and would double-count on this side.
        summaries = ["Dividend"] * 5
        self.assertEqual(external_cashflows(ledger(Summary=summaries))["cashflows"], [])

    def test_a_blank_summary_bank_deposit_is_recovered(self):
        # IG leaves `Summary` empty on some deposits. On the real statement that is one row worth
        # GBP 24,633 of GBP 94,633 -- a quarter of the contributions -- so missing it would not
        # look like a bug, just like outperformance.
        blank_deposit = {
            "TextDate": "31/03/19",
            "Summary": None,
            "MarketName": "Bank Deposit",
            "PL Amount": "1,000.00",
            "Cash transaction": False,
            "DateUtc": "2019-03-31T09:00:00",
            "CurrencyIsoCode": "GBP",
        }
        result = external_cashflows(ledger(extra_rows=[blank_deposit]))

        self.assertEqual(
            result["cashflows"],
            [
                {"date": "2019-03-31", "amount_gbp": 1000.0},
                {"date": "2019-04-01", "amount_gbp": 5000.0},
            ],
        )
        self.assertEqual(result["total_gbp"], 6000.0)

    def test_cashflows_are_returned_in_date_order(self):
        # The accumulation walks closes and cashflows together in one pass, so an out-of-order
        # statement must not leave a deposit applied at the wrong close.
        result = external_cashflows(ledger().iloc[::-1])
        dates = [flow["date"] for flow in result["cashflows"]]
        self.assertEqual(dates, sorted(dates))


class TestAStatementThatCannotBeTrustedYieldsNothing(unittest.TestCase):
    """Every one of these beats charting a line, because an understated deposit history reads as
    outperformance -- an error biased towards flattering the portfolio."""

    def test_a_partial_export_is_refused_rather_than_understated(self):
        # Dropping the founding deposit is exactly the case that matters: the remaining GBP 0 of
        # contributions against a real curve would make any index look beaten.
        result = external_cashflows(ledger().iloc[1:])
        self.assertEqual(result["withheld_reason"], "partial_window")
        self.assertNotIn("cashflows", result)

    def test_an_undated_statement_is_refused(self):
        # Without dates there is no close to buy at.
        result = external_cashflows(ledger(drop=("DateUtc", "TextDate")))
        self.assertEqual(result["withheld_reason"], "undated")

    def test_a_mixed_currency_statement_is_refused(self):
        result = external_cashflows(ledger(CurrencyIsoCode=["GBP", "USD", "GBP", "GBP", "GBP"]))
        self.assertEqual(result["withheld_reason"], "non_gbp")

    def test_a_statement_with_no_summary_column_is_refused_not_read_as_empty(self):
        # Without `Summary` a deposit is indistinguishable from a trade. "No deposits" would be a
        # different and wrong answer.
        result = external_cashflows(ledger(drop=("Summary",)))
        self.assertEqual(result["withheld_reason"], "no_ledger")

    def test_no_statement_at_all_is_refused(self):
        self.assertEqual(external_cashflows(None)["withheld_reason"], "no_ledger")


class TestUnitsAreBoughtWithEachDeposit(unittest.TestCase):
    def test_one_deposit_is_worth_its_cash_on_the_day_it_buys(self):
        result = deposit_matched_series(
            CLOSES, "GBP", [{"date": "2024-01-02", "amount_gbp": 1000.0}]
        )
        # 1000 / 100 = 10 units; 10 x 100 on day one, 10 x 200 after the doubling.
        self.assertEqual(
            result["points"],
            [
                {"date": "2024-01-02", "value": 1000.0},
                {"date": "2024-01-03", "value": 2000.0},
            ],
        )
        self.assertEqual(result["deposits_matched"], 1)
        self.assertEqual(result["total_deposited_gbp"], 1000.0)
        self.assertEqual(result["first_deposit"], "2024-01-02")

    def test_a_later_deposit_buys_at_its_own_price_not_the_first(self):
        result = deposit_matched_series(
            CLOSES,
            "GBP",
            [
                {"date": "2024-01-02", "amount_gbp": 1000.0},
                {"date": "2024-01-03", "amount_gbp": 500.0},
            ],
        )
        # 10 units at 100, then 2.5 more at 200: 12.5 x 200 = 2500, not 1500 x 2.
        self.assertEqual(result["points"][-1], {"date": "2024-01-03", "value": 2500.0})
        self.assertEqual(result["deposits_matched"], 2)
        self.assertEqual(result["total_deposited_gbp"], 1500.0)

    def test_a_weekend_deposit_buys_at_the_next_close(self):
        # Saturday has no close. Buying at Friday's would back-date the purchase into a price the
        # money was not yet there for; dropping it would lose the contribution entirely.
        week = closes(["2024-01-05", "2024-01-08"], [100.0, 110.0])
        result = deposit_matched_series(
            week, "GBP", [{"date": "2024-01-06", "amount_gbp": 1000.0}]
        )
        self.assertEqual(result["points"], [{"date": "2024-01-08", "value": 1000.0}])
        self.assertEqual(result["deposits_matched"], 1)

    def test_a_deposit_predating_the_price_history_still_buys(self):
        result = deposit_matched_series(
            CLOSES, "GBP", [{"date": "2020-01-01", "amount_gbp": 1000.0}]
        )
        self.assertEqual(result["points"][0], {"date": "2024-01-02", "value": 1000.0})

    def test_nothing_is_drawn_before_the_first_deposit(self):
        # A zero-value leg back to the start of the price history would read as the account having
        # been worth nothing for years, rather than not existing yet.
        result = deposit_matched_series(
            CLOSES, "GBP", [{"date": "2024-01-03", "amount_gbp": 1000.0}]
        )
        self.assertEqual([p["date"] for p in result["points"]], ["2024-01-03"])

    def test_a_deposit_after_the_last_close_buys_nothing_and_is_reported_unmatched(self):
        result = deposit_matched_series(
            CLOSES,
            "GBP",
            [
                {"date": "2024-01-02", "amount_gbp": 1000.0},
                {"date": "2030-01-01", "amount_gbp": 9999.0},
            ],
        )
        self.assertEqual(result["deposits_matched"], 1)
        # The unmatched deposit must not be counted as invested, or the caption would claim money
        # the line never held.
        self.assertEqual(result["total_deposited_gbp"], 1000.0)

    def test_a_withdrawal_sells_units_back(self):
        flows = [
            {"date": "2024-01-02", "amount_gbp": 1000.0},
            {"date": "2024-01-03", "amount_gbp": -1000.0},
        ]
        # 10 units at 100, then 5 sold at 200, leaving 5 x 200 = 1000.
        result = deposit_matched_series(CLOSES, "GBP", flows)
        self.assertEqual(result["points"][-1], {"date": "2024-01-03", "value": 1000.0})

    def test_a_withdrawal_cannot_drive_the_holding_negative(self):
        # `PL Amount` is signed and this arithmetic is not a brokerage account: a short index
        # position is not something the owner ever took.
        flows = [
            {"date": "2024-01-02", "amount_gbp": 1000.0},
            {"date": "2024-01-03", "amount_gbp": -99999.0},
        ]
        result = deposit_matched_series(CLOSES, "GBP", flows)
        self.assertTrue(all(point["value"] >= 0 for point in result["points"]))
        self.assertEqual([p["date"] for p in result["points"]], ["2024-01-02"])


class TestTheQuoteUnitCancels(unittest.TestCase):
    """CNX1.L quotes in pence and VUSA.L in pounds, and both must land on the same GBP scale."""

    def test_a_pence_quote_needs_no_conversion(self):
        # Every purchase divides by a close and every valuation multiplies by one, so the unit
        # cancels: value_n = sum of amount_i x (close_n / close_i). Asserted rather than reasoned
        # about, because a 100x error here would look like a plausible benchmark.
        flows = [
            {"date": "2024-01-02", "amount_gbp": 1000.0},
            {"date": "2024-01-03", "amount_gbp": 500.0},
        ]
        pence = closes(["2024-01-02", "2024-01-03"], [10000.0, 20000.0])
        pounds = closes(["2024-01-02", "2024-01-03"], [100.0, 200.0])

        self.assertEqual(
            deposit_matched_series(pence, "GBp", flows)["points"],
            deposit_matched_series(pounds, "GBP", flows)["points"],
        )
        # And in absolute terms: 1500 deposited, worth 2500 after the doubling -- not 25 or
        # 250,000, which is what a stray pence factor would produce.
        self.assertEqual(
            deposit_matched_series(pence, "GBp", flows)["points"][-1]["value"], 2500.0
        )

    def test_a_non_gbp_quote_is_refused(self):
        # This is what the currency check is actually for. Cancelling the quote unit does nothing
        # about a moving exchange rate, so a USD index would need a daily GBP/USD series.
        result = deposit_matched_series(
            CLOSES, "USD", [{"date": "2024-01-02", "amount_gbp": 1000.0}]
        )
        self.assertEqual(result["withheld_reason"], "non_gbp_quote")
        self.assertNotIn("points", result)

    def test_an_unknown_quote_currency_is_refused(self):
        for currency in (None, "", "EUR"):
            result = deposit_matched_series(
                CLOSES, currency, [{"date": "2024-01-02", "amount_gbp": 1000.0}]
            )
            self.assertEqual(result["withheld_reason"], "non_gbp_quote", currency)


class TestNothingToChart(unittest.TestCase):
    def test_no_cashflows_yields_no_series(self):
        self.assertEqual(
            deposit_matched_series(CLOSES, "GBP", [])["withheld_reason"], "no_cashflows"
        )

    def test_no_closes_yields_no_series(self):
        empty = pd.DataFrame(columns=["Date", "close"])
        result = deposit_matched_series(
            empty, "GBP", [{"date": "2024-01-02", "amount_gbp": 1000.0}]
        )
        self.assertEqual(result["withheld_reason"], "no_closes")

    def test_a_series_of_only_unusable_closes_yields_no_series(self):
        # A zero close cannot price a purchase, and dividing by it would produce infinite units.
        unusable = closes(["2024-01-02", "2024-01-03"], [0.0, float("nan")])
        result = deposit_matched_series(
            unusable, "GBP", [{"date": "2024-01-02", "amount_gbp": 1000.0}]
        )
        self.assertEqual(result["withheld_reason"], "no_closes")

    def test_a_single_unusable_close_is_skipped_rather_than_failing_the_series(self):
        gappy = closes(["2024-01-02", "2024-01-03", "2024-01-04"], [100.0, float("nan"), 200.0])
        result = deposit_matched_series(
            gappy, "GBP", [{"date": "2024-01-02", "amount_gbp": 1000.0}]
        )
        self.assertEqual([p["date"] for p in result["points"]], ["2024-01-02", "2024-01-04"])


if __name__ == "__main__":
    unittest.main()
