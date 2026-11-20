"""KAN-40: IG quotes TradeHistory `Price` in minor units, so a fill must be unit-resolved."""
import io
import unittest

import pandas as pd

from backend.app.api.v1.trades import (
    UNKNOWN_FILL,
    extract_trade_activities,
    normalise_fill_price,
)

# Rows copied from a real IG TradeHistory export. `Consideration` is gross and in the same
# currency as `Price`; `Cost/Proceeds` is settled GBP. Corporate actions arrive priced at 0.00,
# and two of them carry a real Price with no Consideration at all.
CSV = """TextDate,Time,Activity,Market,Direction,Quantity,Price,Currency,Consideration,Cost/Proceeds
09-11-2026,15:30:00,TRADE,3M Co (24 Hours),SELL,-15.0,18888.0,USD,2833.20,2096.44
08-04-2026,14:00:00,TRADE,Apple Inc (24 Hours),BUY,5.0,25808.0,USD,-1290.40,-1001.22
19-10-2026,08:15:00,TRADE,Schroders PLC,SELL,-900.0,590.0,GBP,5310.00,5310.00
21-05-2025,09:00:00,TRADE,Carl Zeiss Meditec AG,BUY,10.0,4680.0,EUR,-468.00,-401.50
09-05-2025,10:00:00,CORPORATE ACTION,Barrick Gold Corp,BUY,120.0,0.00,USD,0.0,0.0
07-05-2026,11:00:00,CORPORATE ACTION,Devon Energy Corp,BUY,59.0,3715.36,USD,,
"""


def activities():
    return {a["market"]: a["fill"] for a in extract_trade_activities(pd.read_csv(io.StringIO(CSV)))}


class TestFillPriceNormalisation(unittest.TestCase):
    """The unit is derived from the row's own Consideration / Quantity."""

    def test_usd_minor_units_are_scaled_and_symbol_tagged(self):
        # Regression: these rendered as 18888.0 and 25808.0 — 100x the real execution.
        self.assertEqual(normalise_fill_price(18888.0, -15.0, 2833.20, "USD"), "$188.88")
        self.assertEqual(normalise_fill_price(25808.0, 5.0, -1290.40, "USD"), "$258.08")

    def test_gbx_quoted_lse_holding_becomes_pounds(self):
        self.assertEqual(normalise_fill_price(590.0, -900.0, 5310.00, "GBP"), "£5.90")

    def test_eur_holding_uses_its_own_symbol(self):
        self.assertEqual(normalise_fill_price(4680.0, 10.0, -468.00, "EUR"), "€46.80")

    def test_a_price_already_in_major_units_is_left_alone(self):
        # The scale is derived, not assumed, so a statement quoting whole units still works.
        self.assertEqual(normalise_fill_price(188.88, -15.0, 2833.20, "USD"), "$188.88")

    def test_rounding_in_consideration_does_not_defeat_the_match(self):
        # Consideration is rounded to 2dp, so a scaled Price never matches it exactly.
        self.assertEqual(normalise_fill_price(18800.95, 10.0, -1880.10, "USD"), "$188.01")

    def test_thousands_separator_price_is_not_dropped(self):
        self.assertEqual(normalise_fill_price("25,808.0", 5.0, "-1,290.40", "USD"), "$258.08")

    def test_unknown_currency_falls_back_to_its_code(self):
        self.assertEqual(normalise_fill_price(1234.0, 10.0, 123.40, "CHF"), "12.34 CHF")

    def test_unresolvable_rows_show_the_marker_not_a_raw_figure(self):
        cases = {
            "zero-priced corporate action": (0.0, 120.0, 0.0, "USD"),
            "no consideration to compare against": (3715.36, 59.0, float("nan"), "USD"),
            "missing consideration column": (3715.36, 59.0, None, "USD"),
            "zero quantity": (18888.0, 0.0, 2833.20, "USD"),
            "neither 1x nor 100x fits": (18888.0, -15.0, 500.00, "USD"),
        }
        for label, args in cases.items():
            with self.subTest(label):
                self.assertEqual(normalise_fill_price(*args), UNKNOWN_FILL)


class TestThroughExtractTradeActivities(unittest.TestCase):
    """The scaling has to happen at the boundary, so the emitted payload is already correct."""

    def setUp(self):
        self.fills = activities()

    def test_every_tradeable_row_is_resolved_with_its_currency(self):
        self.assertEqual(self.fills["3M Co (24 Hours)"], "$188.88")
        self.assertEqual(self.fills["Apple Inc (24 Hours)"], "$258.08")
        self.assertEqual(self.fills["Schroders PLC"], "£5.90")
        self.assertEqual(self.fills["Carl Zeiss Meditec AG"], "€46.80")

    def test_corporate_actions_without_a_resolvable_price_show_the_marker(self):
        self.assertEqual(self.fills["Barrick Gold Corp"], UNKNOWN_FILL)
        self.assertEqual(self.fills["Devon Energy Corp"], UNKNOWN_FILL)

    def test_fill_stays_a_string_so_existing_consumers_keep_working(self):
        for market, fill in self.fills.items():
            with self.subTest(market):
                self.assertIsInstance(fill, str)

    def test_a_usd_and_a_gbx_holding_are_both_correct_in_one_payload(self):
        self.assertNotEqual(self.fills["3M Co (24 Hours)"], UNKNOWN_FILL)
        self.assertNotEqual(self.fills["Schroders PLC"], UNKNOWN_FILL)
        self.assertTrue(self.fills["3M Co (24 Hours)"].startswith("$"))
        self.assertTrue(self.fills["Schroders PLC"].startswith("£"))

    def test_settled_value_column_is_untouched(self):
        # `value` is already GBP from Cost/Proceeds; only `fill` was mis-scaled.
        acts = {a["market"]: a["value"] for a in extract_trade_activities(pd.read_csv(io.StringIO(CSV)))}
        self.assertEqual(acts["3M Co (24 Hours)"], "£2,096.44")


if __name__ == "__main__":
    unittest.main()
