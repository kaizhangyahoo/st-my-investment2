"""KAN-56: the settled cash balance netted from an IG transaction statement.

The tile this feeds used to claim brokers do not report cash. They do -- `TransactionHistory*.csv`
is a complete single-currency cash ledger -- but only an export reaching account inception nets
to a balance. A mid-life window nets to a figure that still looks like one, so most of these tests
are about refusing to answer.
"""
import unittest

import pandas as pd

from backend.app.services.portfolio_engine import derive_cash_balance
from test.support.portfolio import TRANSACTION_BALANCE as BALANCE
from test.support.portfolio import transaction_df


def ledger(drop=(), **overrides):
    """The sample ledger as a frame, optionally without some columns or with cells replaced."""
    df = transaction_df()
    for column, values in overrides.items():
        df[column] = values
    return df.drop(columns=list(drop))


class TestAnInceptionLedgerYieldsABalance(unittest.TestCase):
    def setUp(self):
        self.result = derive_cash_balance(ledger())

    def test_the_signed_amounts_net_to_the_balance(self):
        # No sign flip from `Transaction type` is involved: IG signs `PL Amount` itself.
        self.assertEqual(self.result["balance_gbp"], BALANCE)
        self.assertIsNone(self.result.get("withheld_reason"))

    def test_thousands_separator_amounts_are_not_dropped(self):
        # Regression shared with the waterfall: under pandas 3 the column is StringDtype, so an
        # unstripped "5,000.00" coerces to NaN -- which here would withhold the balance entirely.
        self.assertGreater(self.result["balance_gbp"], 1000)

    def test_the_covered_window_is_reported_with_the_figure(self):
        # The tile prints this range; a balance without it cannot be sanity-checked by eye.
        self.assertEqual(self.result["covered_from"], "2019-04-01")
        self.assertEqual(self.result["covered_to"], "2019-04-05")


class TestAPartialWindowIsRefused(unittest.TestCase):
    def test_a_mid_life_export_is_withheld_rather_than_netted(self):
        # Dropping the founding deposit leaves sells and fees with nothing to fund them, so the
        # running balance goes negative -- detectable without trusting the filename.
        mid_life = ledger().iloc[1:]
        result = derive_cash_balance(mid_life)

        self.assertIsNone(result.get("balance_gbp"))
        self.assertEqual(result["withheld_reason"], "partial_window")

    def test_the_window_is_still_reported_so_the_reason_can_be_shown(self):
        result = derive_cash_balance(ledger().iloc[1:])
        self.assertEqual(result["covered_from"], "2019-04-02")
        self.assertEqual(result["covered_to"], "2019-04-05")

    def test_a_balance_that_touches_zero_is_not_treated_as_partial(self):
        # An account spent down to exactly nothing is complete, not clipped. Guards against a
        # float-noise cumsum reading 0.00 as negative.
        drained = ledger(drop=(), **{"PL Amount": ["100.00", "-100.00", "0.00", "0.00", "0.00"]})
        result = derive_cash_balance(drained)

        self.assertEqual(result["balance_gbp"], 0.0)

    def test_rows_within_one_day_are_netted_before_the_check(self):
        # A purchase booked ahead of its own deposit in file order must not read as an overdraft:
        # rows inside a day carry no sequence.
        same_day = ledger(**{
            "DateUtc": ["2019-04-01T09:15:00"] * 2 + ["2019-04-03T11:30:00"] * 3,
            "PL Amount": ["-2,000.00", "5,000.00", "67.55", "-10.00", "1,500.00"],
        })
        result = derive_cash_balance(same_day)

        self.assertEqual(result["balance_gbp"], BALANCE)


class TestTheDateColumn(unittest.TestCase):
    def test_textdate_is_used_when_dateutc_is_absent(self):
        result = derive_cash_balance(ledger(drop=("DateUtc",)))
        self.assertEqual(result["balance_gbp"], BALANCE)

    def test_textdate_is_read_day_first(self):
        # "01/04/19" is 1 April, not 4 January. Reading it the other way round would reorder the
        # ledger and put a sell before its deposit, withholding a sound balance.
        result = derive_cash_balance(ledger(drop=("DateUtc",)))
        self.assertEqual(result["covered_from"], "2019-04-01")
        self.assertEqual(result["covered_to"], "2019-04-05")

    def test_a_column_that_dates_only_some_rows_is_skipped_for_one_that_dates_all(self):
        # The rows a half-parsed column misses are cash movements missing from the coverage
        # check, so a column is used whole or not at all.
        patchy = ledger(**{"DateUtc": ["2019-04-01T09:15:00", "", "", "", ""]})
        result = derive_cash_balance(patchy)

        self.assertEqual(result["balance_gbp"], BALANCE)
        self.assertEqual(result["covered_from"], "2019-04-01")

    def test_no_usable_date_column_withholds_the_balance(self):
        result = derive_cash_balance(ledger(drop=("DateUtc", "TextDate")))

        self.assertIsNone(result.get("balance_gbp"))
        self.assertEqual(result["withheld_reason"], "undated")

    def test_every_date_column_half_parsed_withholds_the_balance(self):
        patchy = ledger(**{
            "DateUtc": ["2019-04-01T09:15:00", "", "", "", ""],
            "TextDate": ["01/04/19", "", "", "", ""],
        })
        self.assertEqual(derive_cash_balance(patchy)["withheld_reason"], "undated")


class TestTheCurrencyGuard(unittest.TestCase):
    def test_a_single_non_gbp_row_withholds_the_balance(self):
        # A bare sum is only a balance while one currency is involved, and the statement carries
        # no rate to convert with.
        mixed = ledger(**{"CurrencyIsoCode": ["GBP", "GBP", "USD", "GBP", "GBP"]})
        result = derive_cash_balance(mixed)

        self.assertIsNone(result.get("balance_gbp"))
        self.assertEqual(result["withheld_reason"], "non_gbp")

    def test_casing_and_padding_do_not_count_as_another_currency(self):
        self.assertEqual(
            derive_cash_balance(ledger(**{"CurrencyIsoCode": [" gbp "] * 5}))["balance_gbp"],
            BALANCE,
        )

    def test_a_missing_currency_column_withholds_the_balance(self):
        # Absent is not the same as GBP: nothing confirms the ledger is single-currency.
        result = derive_cash_balance(ledger(drop=("CurrencyIsoCode",)))
        self.assertEqual(result["withheld_reason"], "non_gbp")


class TestNothingToDeriveFrom(unittest.TestCase):
    def test_no_statement_at_all(self):
        self.assertEqual(derive_cash_balance(None)["withheld_reason"], "no_ledger")

    def test_an_empty_frame(self):
        self.assertEqual(derive_cash_balance(pd.DataFrame())["withheld_reason"], "no_ledger")

    def test_a_frame_with_headers_but_no_rows(self):
        self.assertEqual(
            derive_cash_balance(ledger().iloc[0:0])["withheld_reason"], "no_ledger"
        )

    def test_a_statement_without_the_amount_column(self):
        result = derive_cash_balance(ledger(drop=("PL Amount",)))
        self.assertEqual(result["withheld_reason"], "no_ledger")

    def test_an_unreadable_amount_withholds_rather_than_counting_as_zero(self):
        # The waterfall absorbs these as 0 because a category total is a breakdown, not a claim
        # about cash on hand. A balance cannot: it would be wrong by an unknown amount silently.
        broken = ledger(**{"PL Amount": ["5,000.00", "n/a", "67.55", "-10.00", "1,500.00"]})
        result = derive_cash_balance(broken)

        self.assertIsNone(result.get("balance_gbp"))
        self.assertEqual(result["withheld_reason"], "unreadable_amounts")


if __name__ == "__main__":
    unittest.main()
