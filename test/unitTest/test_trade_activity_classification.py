"""KAN-57: a corporate action in the IG statement must not render as a manual trade.

`extract_trade_activities` derived the badge from `Direction`/`Quantity` alone and dropped the
statement's own `Activity` column, so all 44 of this account's corporate actions -- splits,
mergers and the Schroders scheme of arrangement -- appeared in Trade Activities as ordinary red
SELLs or green BUYs, indistinguishable from orders the user placed.

The direction is still true for those rows, and the side filter, the cost-basis sum and the
inspector chart all key on it, so the fix is additive: `activity` keeps saying BUY/SELL and
`is_corporate_action` carries the provenance.
"""
import io
import unittest

import pandas as pd

from backend.app.api.v1.trades import extract_trade_activities
from backend.app.schemas.portfolio import TradeActivityItem

# Rows copied from the real QX2B3 TradeHistory export. The Schroders row on 2026-10-19 is the one
# the ticket was raised against; the 2022 pair is one event split across a sell and a buy leg, and
# the Barrick row shows that a corporate action can be a BUY.
CSV = """TextDate,Time,Activity,Market,Direction,Quantity,Price,Currency,Consideration,Cost/Proceeds
19-10-2026,05:08:18,CORPORATE ACTION,Schroders PLC,SELL,-900.00,590.00,GBP,5310.00,5310.00
30-08-2023,09:20:43,TRADE,Schroders PLC,BUY,315.00,418.00,GBP,-1316.70,-1331.28
01-11-2022,11:27:10,CORPORATE ACTION,Schroders PLC,SELL,-0.64,2077.25,GBP,13.29,13.29
01-11-2022,11:27:10,CORPORATE ACTION,Schroders PLC,BUY,0.64,0.00,GBP,0.00,0.00
09-05-2025,10:00:00,CORPORATE ACTION,Barrick Gold Corp,BUY,120.00,0.00,USD,0.00,0.00
09-11-2026,15:30:00,TRADE,3M Co (24 Hours),SELL,-15.00,18888.00,USD,2833.20,2096.44
"""


def activities(csv: str = CSV):
    return extract_trade_activities(pd.read_csv(io.StringIO(csv)))


class TestCorporateActionIsMarked(unittest.TestCase):
    def test_the_reported_schroders_row_is_flagged(self):
        row = next(a for a in activities() if a["date"] == "2026-10-19")

        self.assertTrue(row["is_corporate_action"])
        self.assertEqual(row["market"], "Schroders PLC")

    def test_a_real_trade_is_not_flagged(self):
        # The same instrument was also bought outright, and that row must stay a plain BUY.
        row = next(a for a in activities() if a["date"] == "2023-08-30")

        self.assertFalse(row["is_corporate_action"])
        self.assertEqual(row["activity"], "BUY")

    def test_the_direction_is_preserved_rather_than_replaced(self):
        # The regression this guards: overwriting `activity` with "CORP ACTION SELL" would drop
        # these rows out of the SELL side filter and out of the chart's buy/sell marker split.
        flagged = {(a["date"], a["activity"]) for a in activities() if a["is_corporate_action"]}

        self.assertIn(("2026-10-19", "SELL"), flagged)
        self.assertIn(("2025-05-09", "BUY"), flagged, "a corporate action can be a BUY")

    def test_both_legs_of_one_event_are_flagged(self):
        legs = [a for a in activities() if a["date"] == "2022-11-01"]

        self.assertEqual(len(legs), 2)
        self.assertTrue(all(leg["is_corporate_action"] for leg in legs))
        self.assertEqual({leg["activity"] for leg in legs}, {"BUY", "SELL"})

    def test_a_statement_with_no_activity_column_still_loads(self):
        # Older exports omit it. Dropping the column must not make every row a corporate action,
        # and must not raise -- `extract_trade_activities` swallows exceptions and returns [],
        # which would silently empty the panel.
        without = "\n".join(
            ",".join(part for i, part in enumerate(line.split(",")) if i != 2)
            for line in CSV.strip().splitlines()
        )

        rows = activities(without + "\n")

        self.assertEqual(len(rows), 6, "losing the column must not lose the rows")
        self.assertFalse(any(r["is_corporate_action"] for r in rows))

    def test_the_flag_survives_response_model_validation(self):
        # The field is new on a live schema, so the contract is asserted as well as the dict.
        validated = [TradeActivityItem.model_validate(a) for a in activities()]

        self.assertEqual(sum(v.is_corporate_action for v in validated), 4)
        self.assertEqual(sum(1 for v in validated if not v.is_corporate_action), 2)

    def test_the_flag_defaults_to_false_when_absent(self):
        # Sample/fallback data and any older cached payload omit it entirely.
        item = TradeActivityItem.model_validate({
            "qty": 5.0, "fill": "$258.08", "value": "£1,001.22", "date": "2026-04-08",
            "time": "14:00:00", "activity": "BUY", "market": "Apple Inc",
        })

        self.assertFalse(item.is_corporate_action)


if __name__ == "__main__":
    unittest.main()
