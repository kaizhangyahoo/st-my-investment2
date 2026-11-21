"""Realised P&L with corporate actions classified (KAN-52).

Every fixture below is copied verbatim from the real `TradeHistory-QX2B3` statement, because the
shapes that break a naive FIFO are the ones nobody would think to invent: a share split booked as
three zero-cash rows, a merger whose legs carry no `Consideration` at all, and two unrelated
delistings on one date that look like a merger if you pair by date.

The rule under test throughout is that a corporate action is read off the *shape* of its date --
net quantity and net cash -- and never off wording or `Price`. `Price` is deliberately set to its
real unmarked minor-unit value (KAN-40) and nothing here may depend on it.

`TempMappingCase` keeps this offline and off the repo's `company_name_to_ticker.json`: resolution
is a dict lookup against a throwaway file, so no test can reach SEC EDGAR or a price provider.
"""
import unittest

import pandas as pd

from backend.app.services import realised_pnl
from test.support.portfolio import TempMappingCase

NAN = float("nan")

# TextDate, Time, Activity, Market, Quantity, Price, Cost/Proceeds
COLUMNS = ["TextDate", "Time", "Activity", "Market", "Quantity", "Price", "Cost/Proceeds"]

TRADE = "TRADE"
CA = "CORPORATE ACTION"

# Schroders: bought 100, a 2022 share split restated the holding as 585, a fractional entitlement
# was sold for 13.29, another 315 were bought, and the 2026 delisting paid 5310 for all 900.
SCHRODERS = [
    ("21-05-2021", "15:37:09", TRADE, "Schroders PLC", 100.00, 3548.00, -3568.74),
    ("20-09-2022", "06:23:52", CA, "Schroders PLC", 17.00, 0.00, 0.00),
    ("20-09-2022", "07:30:49", CA, "Schroders PLC", -117.00, 0.00, 0.00),
    ("20-09-2022", "07:32:08", CA, "Schroders PLC", 585.00, 0.00, 0.00),
    ("01-11-2022", "11:27:10", CA, "Schroders PLC", -0.64, 2077.25, 13.29),
    ("01-11-2022", "11:27:10", CA, "Schroders PLC", 0.64, 0.00, 0.00),
    ("30-08-2023", "09:20:43", TRADE, "Schroders PLC", 315.00, 418.00, -1331.28),
    ("19-10-2026", "05:08:18", CA, "Schroders PLC", -900.00, 590.00, 5310.00),
]

# Atkore delisted for cash on the same date Schroders did, with nothing arriving in exchange.
ATKORE = [
    ("27-08-2024", "20:47:30", TRADE, "Atkore International Group Inc", 5.0, 9608.0, -364.09),
    ("27-08-2024", "20:54:49", TRADE, "Atkore International Group Inc", 5.0, 9580.0, -363.06),
    ("10-12-2024", "17:22:01", TRADE, "Atkore International Group Inc", 5.0, 8800.0, -346.65),
    ("10-02-2025", "14:56:51", TRADE, "Atkore International Group Inc", 10.0, 6680.0, -542.45),
    ("20-02-2025", "18:18:08", TRADE, "Atkore International Group Inc", 15.0, 6680.0, -795.48),
    ("19-10-2026", "11:34:20", CA, "Atkore International Group Inc", -40.0, 9500.0, 2832.27),
]

# IEA was acquired by MasTec: 220 IEA out for 2075.41 cash, 10 MTZ in at a stated price of zero.
IEA_MASTEC = [
    ("10-03-2021", "16:37:05", TRADE, "Infrastructure and Energy Alternatives Inc", 120.0, 1488.0, -1291.51),
    ("15-04-2021", "15:58:26", TRADE, "Infrastructure and Energy Alternatives Inc", 100.0, 1218.0, -887.59),
    ("10-10-2022", "10:45:49", CA, "Infrastructure and Energy Alternatives Inc", -220.0, 1050.0, 2075.41),
    ("10-10-2022", "10:46:31", CA, "MasTec Inc", 10.00, 0.0, 0.00),
    ("04-11-2022", "10:09:38", CA, "MasTec Inc", -0.62, 6449.0, 35.45),
    ("04-11-2022", "10:09:38", CA, "MasTec Inc", 0.62, 0.0, 0.00),
    ("15-12-2022", "04:47:34", CA, "MasTec Inc", -0.62, 1065.0, 5.38),
    ("15-12-2022", "04:47:34", CA, "MasTec Inc", 0.62, 0.0, 0.00),
    ("01-02-2023", "20:41:16", TRADE, "MasTec Inc", -10.00, 9880.0, 793.58),
]

# Coterra -> Devon. Both legs have an empty `Cost/Proceeds`, and IG renamed the market mid-history
# so the selling leg reads "(24 Hours)" while every buy does not.
COTERRA_DEVON = [
    ("09-11-2022", "20:41:25", TRADE, "Coterra Enercoterra energy Inc", 50.0, 2688.00, -1190.57),
    ("09-12-2022", "18:05:58", TRADE, "Coterra Enercoterra energy Inc", 25.0, 2480.00, -507.21),
    ("06-02-2023", "17:00:04", TRADE, "Coterra Enercoterra energy Inc", 15.0, 2380.00, -298.78),
    ("10-06-2024", "16:37:51", TRADE, "Coterra Enercoterra energy Inc", -5.0, 2818.00, 110.15),
    ("07-05-2026", "04:30:20", CA, "Coterra Enercoterra energy Inc (24 Hours)", -85.0, 2578.89, NAN),
    ("07-05-2026", "04:31:22", CA, "Devon Energy Corp (24 Hours)", 59.0, 3715.36, NAN),
    ("21-05-2026", "10:31:31", CA, "Devon Energy Corp (24 Hours)", 0.5, 0.00, 0.00),
    ("21-05-2026", "10:31:32", CA, "Devon Energy Corp (24 Hours)", -0.5, 4583.00, 16.93),
]

# Solventum arrived as free stock when 3M spun it off; no parent leg appears in this statement, so
# nothing in the file says what the 11 shares cost.
SOLVENTUM = [
    ("01-04-2024", "07:00:35", CA, "Solventum Corp", 11.00, 0.0, 0.00),
    ("11-04-2024", "10:12:06", CA, "Solventum Corp", 0.25, 0.0, 0.00),
    ("11-04-2024", "10:12:08", CA, "Solventum Corp", -0.25, 7005.0, 13.93),
]

MAPPINGS = {
    "Schroders PLC": "SDR.L",
    "Atkore International Group Inc": "ATKR",
    "Infrastructure and Energy Alternatives Inc": "IEA",
    "MasTec Inc": "MTZ",
    "Coterra Enercoterra energy Inc": "CTRA",
    "Coterra Enercoterra energy Inc (24 Hours)": "CTRA",
    "Devon Energy Corp (24 Hours)": "DVN",
    "Solventum Corp": "SOLV",
}


def frame(*row_groups):
    """The statement as IG exports it: newest first, so ordering is never free."""
    rows = [row for group in row_groups for row in group]
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df.iloc[::-1].reset_index(drop=True)


class RealisedCase(TempMappingCase):
    MAPPINGS = MAPPINGS

    def book(self, *row_groups):
        return realised_pnl.compute_disposals(frame(*row_groups))

    def by_ticker(self, *row_groups):
        return realised_pnl.realised_by_ticker(self.book(*row_groups)["disposals"])


class TestSchrodersRegression(RealisedCase):
    """AC1: the split-adjusted figure, not the naive one."""

    def test_realised_pnl_is_the_split_adjusted_figure(self):
        self.assertAlmostEqual(self.by_ticker(SCHRODERS)["SDR.L"], 409.98, places=2)

    def test_the_split_carried_the_cost_basis_across_the_new_share_count(self):
        # The naive reading books the 585 post-split shares as free and charges the final sale only
        # the 2023 purchase, giving 5310.00 - 1331.28 = 3978.72. The 2021 cost has to come with it.
        (disposal,) = self.book(SCHRODERS)["disposals"]
        self.assertAlmostEqual(disposal.cost_gbp, 3568.74 + 1331.28, places=2)
        self.assertAlmostEqual(disposal.proceeds_gbp, 5310.00, places=2)
        self.assertEqual(disposal.quantity, 900.0)

    def test_the_fractional_cash_out_is_recorded_beside_the_pnl_not_inside_it(self):
        # Every row's cash sums to 423.27. Treating the 13.29 fraction as a part-disposal would
        # reduce the basis by it and report exactly that, which is the figure to avoid.
        book = self.book(SCHRODERS)
        self.assertAlmostEqual(sum(r[6] for r in SCHRODERS), 423.27, places=2)
        self.assertAlmostEqual(book["corporate_action_cash_gbp"], 13.29, places=2)
        self.assertAlmostEqual(
            book["disposals"][0].realised_gbp + book["corporate_action_cash_gbp"], 423.27, places=2
        )

    def test_the_zero_cash_split_rows_produce_no_disposal_of_their_own(self):
        # Three rows net +485 with no cash. Read as trades they would close the holding at a loss
        # and reopen it free, which is where the inflated gains came from.
        book = self.book(SCHRODERS)
        self.assertEqual(len(book["disposals"]), 1)
        self.assertEqual(book["corporate_action_rows"], 6)
        self.assertEqual(book["excluded_disposals"], 0)

    def test_the_figures_do_not_depend_on_the_price_column(self):
        # `Price` is in unmarked minor units (KAN-40); `Cost/Proceeds` is GBP net of charges, so
        # the engine must never read the former.
        mangled = [row[:5] + (row[5] * 100 + 7,) + row[6:] for row in SCHRODERS]
        self.assertAlmostEqual(self.by_ticker(mangled)["SDR.L"], 409.98, places=2)


class TestCashExit(RealisedCase):
    def test_a_delisting_that_pays_cash_is_an_ordinary_disposal(self):
        # 2832.27 against 40 shares costing 2411.73.
        (disposal,) = self.book(ATKORE)["disposals"]
        self.assertEqual(disposal.kind, "corporate_action")
        self.assertAlmostEqual(disposal.cost_gbp, 2411.73, places=2)
        self.assertAlmostEqual(disposal.realised_gbp, 420.54, places=2)


class TestMergers(RealisedCase):
    """AC2: a merger leg must not dispose against a cost basis of zero."""

    def test_the_basis_moves_to_the_acquirers_shares_net_of_the_cash_leg(self):
        # 220 IEA cost 2179.10 and returned 2075.41 in cash, so 103.69 of basis follows the 10 MTZ
        # shares. The statement prices those shares at zero, which is not what they cost.
        book = self.book(IEA_MASTEC)
        self.assertEqual([d.ticker for d in book["disposals"]], ["MTZ"])
        (disposal,) = book["disposals"]
        self.assertAlmostEqual(disposal.cost_gbp, 103.69, places=2)
        self.assertAlmostEqual(disposal.realised_gbp, 793.58 - 103.69, places=2)
        self.assertTrue(disposal.included)

    def test_nothing_is_realised_at_the_merger_itself(self):
        # The acquisition is not a sale: the cash is a return of capital and the gain lands when
        # the acquirer's shares are eventually sold.
        self.assertNotIn("IEA", self.by_ticker(IEA_MASTEC))

    def test_legs_with_no_consideration_at_all_still_transfer_the_basis(self):
        # Both Coterra/Devon legs have an empty `Cost/Proceeds`. Read as 0.0 that means "no cash
        # moved", which is exactly right for a pure share-for-share exchange.
        book = self.book(COTERRA_DEVON)
        self.assertEqual([d.ticker for d in book["disposals"]], ["CTRA"])
        self.assertAlmostEqual(book["corporate_action_cash_gbp"], 16.93, places=2)

    def test_the_acquirers_position_is_left_with_a_real_basis(self):
        # 85 Coterra shares cost 1877.50 after the 2024 part-sale, so selling the 59 Devon shares
        # they became is charged that -- not the zero the statement prices the new shares at.
        sale = [("01-06-2026", "14:00:00", TRADE, "Devon Energy Corp (24 Hours)", -59.0, 4200.0, 2500.00)]
        (disposal,) = self.book(COTERRA_DEVON, sale)["disposals"][1:]
        self.assertEqual(disposal.ticker, "DVN")
        self.assertAlmostEqual(disposal.cost_gbp, 1877.50, places=2)
        self.assertTrue(disposal.included)

    def test_a_rename_mid_history_does_not_close_the_position(self):
        # The selling leg reads "(24 Hours)" and every buy does not. Grouping by `Market` would
        # make the sale look like a short of an instrument never bought.
        book = self.book(COTERRA_DEVON)
        self.assertEqual(book["excluded_disposals"], 0)
        self.assertEqual(book["excluded_tickers"], [])

    def test_two_delistings_on_one_date_are_not_paired_as_a_merger(self):
        # Atkore and Schroders both delisted for cash on 2026-10-19 with nothing arriving. Pairing
        # by date alone invents a merger between two unrelated holdings and loses one of the gains.
        totals = self.by_ticker(SCHRODERS, ATKORE)
        self.assertAlmostEqual(totals["SDR.L"], 409.98, places=2)
        self.assertAlmostEqual(totals["ATKR"], 420.54, places=2)


class TestUnderivableBasis(RealisedCase):
    """AC4: free stock with no parent leg is flagged, never valued at zero."""

    def test_a_spin_off_with_no_parent_leg_is_flagged_rather_than_priced_at_zero(self):
        book = self.book(SOLVENTUM)
        self.assertEqual(book["disposals"], [])
        # The 13.93 fraction is real cash, so it is reported -- just not as a 13.93 profit.
        self.assertAlmostEqual(book["corporate_action_cash_gbp"], 13.93, places=2)

    def test_selling_the_free_stock_is_excluded_instead_of_booked_as_pure_profit(self):
        sale = [("02-05-2024", "14:00:00", TRADE, "Solventum Corp", -10.75, 7200.0, 620.00)]
        book = self.book(SOLVENTUM, sale)
        (disposal,) = book["disposals"]
        self.assertFalse(disposal.included)
        self.assertEqual(disposal.excluded_reason, "no cost basis in this statement")
        self.assertEqual(book["excluded_tickers"], ["SOLV"])
        self.assertEqual(book["excluded_disposals"], 1)
        # A 620.00 gain against a zero basis is the number this must not report.
        self.assertEqual(realised_pnl.realised_by_ticker(book["disposals"]), {})


class TestWindows(RealisedCase):
    def disposals(self):
        return self.book(SCHRODERS, ATKORE, IEA_MASTEC, COTERRA_DEVON)["disposals"]

    def test_win_rate_counts_winning_disposals_against_closed_disposals(self):
        # Four closed disposals: Schroders, Atkore and MasTec gained, the 2024 Coterra part-sale
        # lost 8.91 (110.15 proceeds against 119.06 of basis).
        result = realised_pnl.realised_for(self.disposals())
        self.assertEqual(result["disposals"], 4)
        self.assertEqual(result["winning_disposals"], 3)
        self.assertAlmostEqual(result["win_rate_pct"], 75.0, places=6)

    def test_the_window_reports_the_bounds_its_disposals_actually_span(self):
        result = realised_pnl.realised_for(self.disposals())
        self.assertEqual(result["start_date"], "2023-02-01")
        self.assertEqual(result["end_date"], "2026-10-19")

    def test_a_window_is_inclusive_at_both_ends(self):
        result = realised_pnl.realised_for(self.disposals(), "2026-10-19", "2026-10-19")
        self.assertEqual(result["disposals"], 2)

    def test_an_empty_window_reports_nulls_rather_than_a_zero_percent_win_rate(self):
        # A 0% win rate reads as "every trade lost", which is a figure no data supports.
        result = realised_pnl.realised_for(self.disposals(), "2027-01-01", "2027-12-31")
        self.assertEqual(result["disposals"], 0)
        self.assertIsNone(result["win_rate_pct"])
        self.assertIsNone(result["realised_pnl_gbp"])
        self.assertIsNone(result["start_date"])
        self.assertIsNone(result["end_date"])

    def test_every_timeframe_the_client_offers_is_present(self):
        windows = realised_pnl.all_windows(self.disposals())
        self.assertEqual(sorted(windows), sorted(["1M", "3M", "6M", "1Y", "ALL"]))
        for timeframe, window in windows.items():
            self.assertEqual(window["timeframe"], timeframe)

    def test_each_window_is_measured_back_from_the_last_disposal(self):
        # Not from the last stored portfolio value: the statement and the value series end on
        # different dates, and anchoring to the series would hide recent trades behind an account
        # that simply has not been recomputed.
        windows = realised_pnl.all_windows(self.disposals())
        self.assertEqual(windows["1M"]["disposals"], 2)
        self.assertEqual(windows["1M"]["start_date"], "2026-10-19")
        self.assertEqual(windows["ALL"]["disposals"], 4)

    def test_no_disposals_at_all_yields_nulls_in_every_timeframe(self):
        for timeframe, window in realised_pnl.all_windows([]).items():
            self.assertIsNone(window["win_rate_pct"], timeframe)
            self.assertIsNone(window["realised_pnl_gbp"], timeframe)
            self.assertEqual(window["disposals"], 0, timeframe)


class TestStatementShape(RealisedCase):
    def test_an_empty_statement_is_empty_rather_than_an_error(self):
        book = realised_pnl.compute_disposals(pd.DataFrame(columns=COLUMNS))
        self.assertEqual(book["disposals"], [])
        self.assertEqual(book["corporate_action_rows"], 0)
        self.assertEqual(book["corporate_action_cash_gbp"], 0.0)

    def test_a_frame_without_the_statement_columns_is_empty_rather_than_an_error(self):
        book = realised_pnl.compute_disposals(pd.DataFrame({"Something": [1, 2]}))
        self.assertEqual(book["disposals"], [])

    def test_a_bom_on_the_first_header_does_not_hide_the_date_column(self):
        # IG writes the export as UTF-8 with a BOM, so the header is "﻿TextDate".
        df = frame(SCHRODERS).rename(columns={"TextDate": "﻿TextDate"})
        self.assertAlmostEqual(
            realised_pnl.realised_by_ticker(realised_pnl.compute_disposals(df)["disposals"])["SDR.L"],
            409.98,
            places=2,
        )

    def test_an_unmapped_market_is_dropped_rather_than_grouped_under_a_blank_ticker(self):
        unmapped = [("01-06-2024", "10:00:00", TRADE, "Nowhere Ltd", -5.0, 100.0, 500.00)]
        self.assertEqual(self.book(unmapped)["disposals"], [])

    def test_dates_are_read_day_first(self):
        # "01-11-2022" is 1 November, not 11 January; month-first parsing reorders the split and
        # the fractional cash-out and changes the basis the final sale is charged.
        rows = realised_pnl._prepare(frame(SCHRODERS))
        self.assertEqual(list(rows["date"])[:2], ["2021-05-21", "2022-09-20"])
        self.assertEqual(list(rows["date"])[-1], "2026-10-19")

    def test_a_buy_and_a_sell_on_one_date_consume_lots_in_clock_order(self):
        same_day = [
            ("01-06-2024", "09:00:00", TRADE, "Schroders PLC", 10.0, 100.0, -100.00),
            ("01-06-2024", "15:00:00", TRADE, "Schroders PLC", 20.0, 100.0, -400.00),
            ("01-06-2024", "16:00:00", TRADE, "Schroders PLC", -10.0, 100.0, 150.00),
        ]
        (disposal,) = self.book(same_day)["disposals"]
        # FIFO on the 09:00 lot costs 100.00; file order would charge it the 15:00 lot's 200.00.
        self.assertAlmostEqual(disposal.cost_gbp, 100.00, places=2)


if __name__ == "__main__":
    unittest.main()
