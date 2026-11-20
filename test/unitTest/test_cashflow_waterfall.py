"""KAN-39: cashflow waterfall categories and amounts from an IG Transaction*.csv."""
import io
import unittest

import pandas as pd

from backend.app.services.portfolio_engine import calculate_cashflow_waterfall

# Shape of a real IG TransactionHistory export: amounts >= 1,000 carry a thousands separator,
# and interest, Section 31 fees, custody fees and some deposits arrive with a blank Summary.
CSV = """Summary,MarketName,PL Amount
Cash In,Card payment ****1234,"5,000.00"
,Bank Deposit,"24,633.00"
Dividend,Lam Research Corp DIVIDEND 320@0.33,67.55
Client Consideration,3M Co CONS 15@18888,"2,096.48"
Client Consideration,Atkore CONS 40@9500,"-3,000.00"
Share Dealing Commissions,Lumentum COMM,-10.00
SDRT,Schroders PLC SDRT,-6.58
,Cash Interest Paid To Client - Nov26,1.03
,3M Co (24 Hours) Section 31 Fee 07CLE:1,-0.04
,Correction RTX Corporation Section 31 Fee 07CLE:2,0.01
,Custody Fee -  <Q3 2023>,-6.00
,Something IG has not labelled,1.50
"""


class TestCashflowWaterfall(unittest.TestCase):
    def setUp(self):
        items = calculate_cashflow_waterfall(pd.read_csv(io.StringIO(CSV)))
        self.by_cat = {i["category"]: i["amount"] for i in items}

    def test_thousands_separator_amounts_are_not_zeroed(self):
        # Regression: under pandas 3 the column is StringDtype, not object, so a dtype-gated
        # comma strip was skipped and every amount >= 1,000 coerced to 0.
        self.assertAlmostEqual(self.by_cat["Cash In"], 29633.00)
        self.assertAlmostEqual(self.by_cat["Client Consideration"], -903.52)

    def test_blank_summary_rows_are_classified_from_market_name(self):
        self.assertAlmostEqual(self.by_cat["Cash Interest"], 1.03)
        self.assertAlmostEqual(self.by_cat["Section 31 Fee"], -0.03)
        self.assertAlmostEqual(self.by_cat["Custody Fee"], -6.00)
        self.assertAlmostEqual(self.by_cat["Uncategorised"], 1.50)

    def test_fees_keep_the_statement_sign(self):
        self.assertLess(self.by_cat["Share Dealing Commissions"], 0)
        self.assertLess(self.by_cat["SDRT"], 0)

    def test_no_row_is_dropped(self):
        self.assertAlmostEqual(sum(self.by_cat.values()), 28776.95)


if __name__ == "__main__":
    unittest.main()
