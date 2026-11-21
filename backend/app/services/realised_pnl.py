"""Per-disposal realised P&L over an IG trade statement, with corporate actions classified (KAN-52).

Pure functions over the `TradeHistory-*.csv` frame: no provider calls, no file writes. A naive FIFO
over the same 339-row statement reported 76.8% / £4,432.34 because 44 rows are
`Activity = CORPORATE ACTION` and 31 of those carry no cash, so the free leg of a share split
became free stock and inflated every later gain. Classifying the event first is the whole job.

Two columns settle most of it:

* `Cost/Proceeds` is the **signed GBP cash impact, already net of `Commission` and `Charges`** --
  a 100-share Schroders buy at 3548p books `-3548.00 - 3.00 - 17.74 = -3568.74`. So it is used
  verbatim and no FX is applied. `Price` is never read, which is what keeps IG's unmarked minor
  units (KAN-40) out of this module entirely.
* Rows group by **resolved ticker, not `Market`**. IG renames a market across sessions
  ("Synopsys Inc" vs "Synopsys Inc (24 Hours)") and across company renames
  ("VG Acquisition Corporation (Ord)" vs "23ANDME Holding Co"); FIFO over the raw name would
  close the old position and open a basis-less new one on every rename. All 339 rows resolve,
  collapsing 78 market names to 58 tickers, and no ticker then goes short.

What a corporate action means is read off the shape of its statement date, never off the wording:

| Date's shape, per ticker        | Reading                | Effect on the books                        |
| ------------------------------- | ---------------------- | ------------------------------------------ |
| net qty 0, no cash              | re-designation         | nothing                                    |
| net qty 0, cash                 | fractional cash-out    | cash recorded, basis untouched, no disposal|
| net qty != 0, no cash           | split / consolidation  | lots rescaled, total basis held constant   |
| net qty != 0, cash              | cash exit              | ordinary FIFO disposal                     |
| one selling + one buying ticker | merger                 | basis moves to the acquirer's new shares   |

A fractional cash-out leaves the basis alone rather than reducing it. That is the difference
between Schroders' naive £423.27 and its true £409.98: the £13.29 fraction is cash the position
threw off, not a part-disposal of it.

A merger moves the disposed basis onto the shares received and treats any cash in the selling leg
as a return of capital, because the statement prices the new shares at 0.00 and splitting the
basis by market value would need a quote this module is not allowed to fetch. Nothing is realised
at the merger itself; the eventual sale of the acquirer's shares realises it against a real basis.

Where no basis can be derived at all -- a spin-off that arrives as free stock with no parent leg,
such as the 11 Solventum shares 3M distributed -- the ticker is flagged and its disposals are
excluded from both figures rather than booked against zero. An excluded disposal is reported, so
the tile can say what it left out instead of quietly understating the count (KAN-18, KAN-19).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.app.services.risk_metrics import TIMEFRAME_MONTHS, TIMEFRAMES
from backend.app.services.ticker_service import load_ticker_mappings, resolve_ticker

CORPORATE_ACTION = "CORPORATE ACTION"

# Quantities are stated to 2dp and cash to the penny, so these separate "zero" from rounding dust
# without ever being large enough to absorb a real fractional leg (the smallest here is 0.25).
_QTY_EPS = 1e-6
_CASH_EPS = 0.005


@dataclass
class _Lot:
    """Shares bought together, and the GBP they cost. `cost` is positive."""

    quantity: float
    cost: float


@dataclass
class _Position:
    lots: List[_Lot] = field(default_factory=list)
    # False once something happened that this statement cannot put a cost on. Sticky: every later
    # disposal of the ticker inherits it, because the unpriced shares are mixed into the lots.
    basis_known: bool = True

    @property
    def quantity(self) -> float:
        return sum(lot.quantity for lot in self.lots)

    @property
    def cost(self) -> float:
        return sum(lot.cost for lot in self.lots)


@dataclass
class Disposal:
    """One closing event and the P&L it realised. `included` gates it out of the aggregates."""

    date: str
    ticker: str
    market: str
    quantity: float
    proceeds_gbp: float
    cost_gbp: float
    realised_gbp: float
    kind: str
    included: bool = True
    excluded_reason: Optional[str] = None


def _take(position: _Position, quantity: float) -> float:
    """Remove `quantity` shares oldest-first and return the GBP basis they carried."""
    remaining = quantity
    basis = 0.0
    while remaining > _QTY_EPS and position.lots:
        lot = position.lots[0]
        if lot.quantity - remaining <= _QTY_EPS:
            basis += lot.cost
            remaining -= lot.quantity
            position.lots.pop(0)
        else:
            share = remaining / lot.quantity
            basis += lot.cost * share
            lot.cost -= lot.cost * share
            lot.quantity -= remaining
            remaining = 0.0
    if remaining > _QTY_EPS:
        # Selling shares the statement never recorded buying. The window starts in 2018, so an
        # older holding is plausible -- but its cost is not in the file and cannot be guessed.
        position.basis_known = False
    return basis


def _rescale(position: _Position, new_quantity: float) -> None:
    """Spread the existing basis over a new share count, as a split or consolidation does."""
    current = position.quantity
    if current <= _QTY_EPS or new_quantity <= _QTY_EPS:
        # Shares appearing where nothing was held: a spin-off, not a split of this holding.
        position.lots = [_Lot(quantity=new_quantity, cost=0.0)]
        position.basis_known = False
        return
    factor = new_quantity / current
    for lot in position.lots:
        lot.quantity *= factor


def _prepare(df_trade_history: pd.DataFrame) -> pd.DataFrame:
    """The statement reduced to what FIFO needs, oldest first.

    IG exports newest-first with `TextDate` as DD-MM-YYYY and a separate `Time`; the two are
    combined so that the four dates holding both a buy and a sell of one ticker consume lots in
    the order they actually happened rather than in file order.
    """
    df = df_trade_history.copy()
    df.columns = [str(c).lstrip("﻿") for c in df.columns]
    if "TextDate" not in df.columns or "Market" not in df.columns:
        return pd.DataFrame(columns=["when", "date", "ticker", "market", "quantity", "cash", "is_ca"])

    times = df["Time"].astype(str) if "Time" in df.columns else "00:00:00"
    df["when"] = pd.to_datetime(
        df["TextDate"].astype(str) + " " + times, errors="coerce", dayfirst=True
    )
    df.loc[df["when"].isna(), "when"] = pd.to_datetime(
        df["TextDate"], errors="coerce", dayfirst=True
    )

    ticker_map = load_ticker_mappings()
    df["ticker"] = df["Market"].map(lambda name: resolve_ticker(name, ticker_map))
    df["market"] = df["Market"].astype(str)
    df["quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    # NaN cash is a real shape (the Coterra/Devon merger legs carry no consideration at all) and
    # means "no cash moved", which is exactly how a basis-transfer leg should read.
    df["cash"] = pd.to_numeric(df.get("Cost/Proceeds"), errors="coerce").fillna(0.0)
    activity = df["Activity"].astype(str).str.upper() if "Activity" in df.columns else ""
    df["is_ca"] = activity == CORPORATE_ACTION

    df = df.dropna(subset=["when", "ticker", "quantity"])
    df["date"] = df["when"].dt.strftime("%Y-%m-%d")
    return df[["when", "date", "ticker", "market", "quantity", "cash", "is_ca"]].sort_values(
        "when", kind="stable"
    )


def _apply_trade(
    row: Any, positions: Dict[str, _Position], disposals: List[Disposal]
) -> None:
    position = positions.setdefault(row.ticker, _Position())
    if row.quantity > 0:
        position.lots.append(_Lot(quantity=row.quantity, cost=-row.cash))
        return
    quantity = abs(row.quantity)
    basis = _take(position, quantity)
    disposals.append(
        _disposal(row.date, row.ticker, row.market, quantity, row.cash, basis, "trade", position)
    )


def _disposal(
    date: str,
    ticker: str,
    market: str,
    quantity: float,
    proceeds: float,
    basis: float,
    kind: str,
    position: _Position,
) -> Disposal:
    return Disposal(
        date=date,
        ticker=ticker,
        market=market,
        quantity=quantity,
        proceeds_gbp=proceeds,
        cost_gbp=basis,
        realised_gbp=proceeds - basis,
        kind=kind,
        included=position.basis_known,
        excluded_reason=None if position.basis_known else "no cost basis in this statement",
    )


def _apply_merger(
    date: str,
    sell: Any,
    buy: Any,
    positions: Dict[str, _Position],
    disposals: List[Disposal],
) -> None:
    """Move the disposed basis onto the shares received, net of any cash the selling leg paid."""
    source = positions.setdefault(sell["ticker"], _Position())
    target = positions.setdefault(buy["ticker"], _Position())
    basis = _take(source, abs(sell["quantity"]))
    known = source.basis_known
    transferred = basis - sell["cash"]

    if transferred < 0:
        # Cash alone exceeded the basis, so the excess is genuinely realised here and the new
        # shares start from nothing -- which has to be flagged, not left to look like a real basis.
        target.lots.append(_Lot(quantity=buy["quantity"], cost=0.0))
        target.basis_known = False
        disposals.append(
            _disposal(
                date, sell["ticker"], sell["market"], abs(sell["quantity"]),
                sell["cash"], basis, "corporate_action", source,
            )
        )
        return

    target.lots.append(_Lot(quantity=buy["quantity"], cost=transferred))
    if not known:
        target.basis_known = False


def _apply_corporate_action(
    date: str,
    group: pd.DataFrame,
    positions: Dict[str, _Position],
    disposals: List[Disposal],
    cash_events: List[Dict[str, Any]],
) -> None:
    per_ticker = group.groupby("ticker").agg(
        quantity=("quantity", "sum"), cash=("cash", "sum"), market=("market", "last")
    )
    selling = per_ticker[per_ticker["quantity"] < -_QTY_EPS]
    buying = per_ticker[per_ticker["quantity"] > _QTY_EPS]

    # A merger is one instrument leaving and one arriving. Two instruments leaving on the same day
    # with no arrival is two unrelated cash exits -- the shape 2026-10-19 has, where Atkore and
    # Schroders both delisted, and where pairing by date alone would invent a merger between them.
    if len(selling) == 1 and len(buying) == 1 and selling.index[0] != buying.index[0]:
        sell = {**selling.iloc[0].to_dict(), "ticker": selling.index[0]}
        buy = {**buying.iloc[0].to_dict(), "ticker": buying.index[0]}
        _apply_merger(date, sell, buy, positions, disposals)
        return

    for ticker, row in per_ticker.iterrows():
        position = positions.setdefault(ticker, _Position())
        net = row["quantity"]
        cash = row["cash"]
        if abs(net) <= _QTY_EPS:
            if abs(cash) > _CASH_EPS:
                # Cash thrown off without changing the holding: a fractional entitlement sold for
                # the account. Reducing the basis by it would turn Schroders' £409.98 into the
                # naive £423.27, so it is recorded beside the P&L, not inside it.
                cash_events.append({"date": date, "ticker": ticker, "amount_gbp": float(cash)})
            continue
        if abs(cash) <= _CASH_EPS:
            _rescale(position, position.quantity + net)
            continue
        quantity = abs(net)
        basis = _take(position, quantity)
        disposals.append(
            _disposal(
                date, str(ticker), str(row["market"]), quantity, float(cash), basis,
                "corporate_action", position,
            )
        )


def compute_disposals(df_trade_history: pd.DataFrame) -> Dict[str, Any]:
    """Every disposal in the statement, oldest first, plus what had to be left out."""
    rows = _prepare(df_trade_history)
    positions: Dict[str, _Position] = {}
    disposals: List[Disposal] = []
    cash_events: List[Dict[str, Any]] = []

    if not rows.empty:
        for date, day in rows.groupby("date", sort=True):
            actions = day[day["is_ca"]]
            if not actions.empty:
                _apply_corporate_action(str(date), actions, positions, disposals, cash_events)
            for row in day[~day["is_ca"]].itertuples():
                _apply_trade(row, positions, disposals)

    corporate_actions = int(rows["is_ca"].sum()) if not rows.empty else 0
    excluded = sorted({d.ticker for d in disposals if not d.included})
    return {
        "disposals": disposals,
        "corporate_action_rows": corporate_actions,
        "corporate_action_cash_gbp": float(sum(e["amount_gbp"] for e in cash_events)),
        "corporate_action_cash_events": cash_events,
        "excluded_tickers": excluded,
        "excluded_disposals": sum(1 for d in disposals if not d.included),
    }


def realised_for(
    disposals: List[Disposal], start_date: Optional[str] = None, end_date: Optional[str] = None
) -> Dict[str, Any]:
    """Aggregate the disposals falling in a date window, inclusive at both ends.

    Only disposals with a derivable basis count. A window holding none reports nulls, so the tile
    shows a dash rather than a 0% win rate that would read as "every trade lost".
    """
    selected = [
        d
        for d in disposals
        if d.included
        and (start_date is None or d.date >= start_date)
        and (end_date is None or d.date <= end_date)
    ]
    if not selected:
        return {
            "disposals": 0,
            "winning_disposals": 0,
            "win_rate_pct": None,
            "realised_pnl_gbp": None,
            # Null rather than the requested bounds: an empty window covered no disposals, so
            # naming a period would describe one it has nothing to say about.
            "start_date": None,
            "end_date": None,
        }
    winners = sum(1 for d in selected if d.realised_gbp > 0)
    return {
        "disposals": len(selected),
        "winning_disposals": winners,
        "win_rate_pct": winners / len(selected) * 100.0,
        "realised_pnl_gbp": sum(d.realised_gbp for d in selected),
        "start_date": min(d.date for d in selected),
        "end_date": max(d.date for d in selected),
    }


def all_windows(disposals: List[Disposal]) -> Dict[str, Dict[str, Any]]:
    """Realised aggregates per timeframe, each cut back from the last disposal.

    Measured from the last disposal rather than from the last stored portfolio value, because the
    statement and the value series end on different dates and anchoring to the series would hide
    recent trades behind an account that simply has not been recomputed. Each window reports the
    bounds it actually covered, so the tile can state its own period instead of borrowing the
    curve's (KAN-27).
    """
    included = [d for d in disposals if d.included]
    last = max((d.date for d in included), default=None)
    windows: Dict[str, Dict[str, Any]] = {}
    for timeframe in TIMEFRAMES:
        months = TIMEFRAME_MONTHS.get(timeframe)
        start = None
        if last is not None and months is not None:
            start = (pd.Timestamp(last) - pd.DateOffset(months=months)).strftime("%Y-%m-%d")
        windows[timeframe] = {
            **realised_for(disposals, start, None),
            "timeframe": timeframe,
        }
    return windows


def realised_by_ticker(disposals: List[Disposal]) -> Dict[str, float]:
    """Total realised P&L per ticker, for reconciling a single instrument against a statement."""
    totals: Dict[str, float] = {}
    for d in disposals:
        if d.included:
            totals[d.ticker] = totals.get(d.ticker, 0.0) + d.realised_gbp
    return totals
