"""Deposit-matched index comparison for the equity curve.

The equity curve tracks a portfolio fed by deposits spread over years, so scaling an index onto
its opening value does not compare the two -- it answers "what if one lump sum had been invested
on day one", which is a different question and a far smaller number. On the reference account it
read as a 100x outperformance where the honest figure is x2.65 against x2.02.

What this builds instead: each deposit buys the index at the next available close, and the series
is the running market value of those units. Deposits are the only input, because a benchmark that
also matched trades, dividends or fees would be reinvesting money the index never paid.

Kept free of FastAPI and of any provider so the arithmetic is testable offline.
"""
from typing import Any, Dict, List, Optional

import pandas as pd

# Quote currencies that need no conversion, which is every spelling of pounds and pence Yahoo
# uses for an LSE listing.
#
# No pence-to-pounds factor is applied, and none is needed: every purchase divides by a close and
# every valuation multiplies by one, so the quote unit cancels --
# `value_n = sum_i amount_i * (close_n / close_i)`. A pence series and the same series in pounds
# produce identical GBP values, which `test_deposit_matched_benchmark.py` asserts directly.
#
# So this set is a guard, not a scale. What it rejects is the case that genuinely cannot be
# handled: a USD-quoted index needs a daily GBP/USD series to be comparable with a GBP-valued
# portfolio, and cancelling the unit does nothing about a moving exchange rate.
GBP_QUOTES = {'GBP', 'GBp', 'GBX', 'GBx'}

# Why no comparison line could be built. Each has to beat drawing a line anyway, because a
# benchmark that is wrong by a currency factor still looks like a benchmark.
BENCHMARK_WITHHELD_NON_GBP_QUOTE = "non_gbp_quote"
BENCHMARK_WITHHELD_NO_CLOSES = "no_closes"
BENCHMARK_WITHHELD_NO_CASHFLOWS = "no_cashflows"


def deposit_matched_series(
    closes: Optional[pd.DataFrame],
    currency: Optional[str],
    cashflows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Market value of index units bought with each cashflow, or why the series was withheld.

    `closes` is a `Date`/`close` frame as `get_price_history` returns it; `cashflows` are
    `{date, amount_gbp}` dicts from `portfolio_engine.external_cashflows`.

    Each cashflow is applied at the first close **on or after** its date, so a Saturday deposit
    buys at Monday's close rather than being dropped or back-dated to Friday. A cashflow dated
    after the last close buys nothing, and `deposits_matched` reports how many were actually
    applied so the caller can say so.

    Only a GBP or GBp quote is accepted. A USD-quoted index would need a daily FX series to be
    comparable with a GBP-valued portfolio, and avoiding exactly that is why the LSE trackers are
    used in the first place. Pence quotes need no conversion -- see `GBP_QUOTES`.
    """
    if str(currency) not in GBP_QUOTES:
        return {"withheld_reason": BENCHMARK_WITHHELD_NON_GBP_QUOTE}
    if not cashflows:
        return {"withheld_reason": BENCHMARK_WITHHELD_NO_CASHFLOWS}

    if closes is None or closes.empty:
        return {"withheld_reason": BENCHMARK_WITHHELD_NO_CLOSES}
    # A zero or missing close cannot price a purchase, so it is dropped rather than dividing by it.
    priced = [
        (pd.Timestamp(row.Date).strftime('%Y-%m-%d'), float(row.close))
        for row in closes.itertuples()
        if pd.notnull(row.Date) and pd.notnull(row.close) and float(row.close) > 0
    ]
    if not priced:
        return {"withheld_reason": BENCHMARK_WITHHELD_NO_CLOSES}
    priced.sort(key=lambda row: row[0])

    pending = sorted(cashflows, key=lambda flow: flow['date'])
    units = 0.0
    matched = 0
    points = []
    for date, close in priced:
        while matched < len(pending) and pending[matched]['date'] <= date:
            delta = float(pending[matched]['amount_gbp']) / close
            # The statement's amounts are signed, so a withdrawal sells units. It cannot sell more
            # than is held: that would mean a short index position nobody ever took.
            units = max(0.0, units + delta)
            matched += 1
        # Nothing is drawn before the first deposit lands. A zero-value leg back to the start of
        # the price history would read as the portfolio having been worth nothing for years.
        if units > 0:
            points.append({"date": date, "value": round(units * close, 2)})

    return {
        "points": points,
        "deposits_matched": matched,
        "total_deposited_gbp": round(
            sum(float(flow['amount_gbp']) for flow in pending[:matched]), 2
        ),
        "first_deposit": pending[0]['date'],
    }
