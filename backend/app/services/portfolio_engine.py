import logging
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from backend.app.services.market_service import get_current_prices, get_historical_fx
from backend.app.services.ticker_service import load_ticker_mappings, resolve_ticker, find_unresolved_symbols
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

def empty_data_quality() -> Dict[str, Any]:
    """The all-clear shape, for responses where no price fetch was attempted."""
    return {"degraded": False, "fx_fallback": False, "unpriced_tickers": [], "failures": []}

def convert_to_gbp(row: pd.Series, gbpusd_rate: float, gbpeur_rate: float) -> float:
    ticker = str(row.name) if hasattr(row, 'name') else str(row.get('Ticker', ''))
    val = float(row.get('Market Value', 0))
    if ticker.endswith('.L'):
        return val
    elif ticker.endswith('.DE'):
        return val / gbpeur_rate if gbpeur_rate else val
    else:
        return val / gbpusd_rate if gbpusd_rate else val

def calculate_positions_from_df(df_trade_history: pd.DataFrame) -> Dict[str, Any]:
    ticker_map = load_ticker_mappings()
    df = df_trade_history.copy()
    if 'TextDate' in df.columns:
        df['Date'] = pd.to_datetime(df['TextDate'], errors='coerce', dayfirst=True)

    df['Ticker'] = df['Market'].map(lambda name: resolve_ticker(name, ticker_map))
    df_valid = df[df['Ticker'].notnull()].copy()

    unresolved_symbols = find_unresolved_symbols(df['Market'].tolist())
    excluded_row_count = int(len(df) - len(df_valid))

    if df_valid.empty:
        return {
            "total_market_value_gbp": 0.0,
            "total_invested_cash": 0.0,
            "total_pnl_gbp": 0.0,
            "currency_allocation": {"usd_gbp": 0.0, "eur_gbp": 0.0, "gbp": 0.0, "total_gbp": 0.0},
            "positions": [],
            "unresolved_symbols": unresolved_symbols,
            "excluded_row_count": excluded_row_count,
            "data_quality": empty_data_quality(),
        }

    grouped = df_valid.groupby('Ticker').agg({
        'Quantity': 'sum',
        'Market': 'last',
        'Cost/Proceeds': 'sum',
        'Charges': 'sum',
        'Commission': 'sum',
        'Currency': 'last'
    })
    grouped = grouped[grouped['Quantity'] != 0].copy()

    grouped['Costs'] = grouped['Cost/Proceeds'] + grouped['Charges'] + grouped['Commission']
    current_prices, price_failures = get_current_prices(grouped.index.tolist())
    grouped['Current Price'] = grouped.index.map(current_prices)
    grouped['Quantity'] = pd.to_numeric(grouped['Quantity'], errors='coerce')
    grouped['Current Price'] = pd.to_numeric(grouped['Current Price'], errors='coerce').fillna(0)
    grouped['Market Value'] = grouped['Quantity'] * grouped['Current Price']

    unpriced = sorted(str(t) for t in grouped.index[grouped['Current Price'] == 0])
    if unpriced:
        logger.warning(
            "No price from any provider for %d ticker(s): %s. "
            "Market value, P&L and totals are understated.",
            len(unpriced),
            ", ".join(unpriced),
        )

    # FX conversion
    min_date = df_valid['Date'].min() if 'Date' in df_valid.columns else datetime.now() - timedelta(days=365)
    start_str = min_date.strftime('%Y-%m-%d') if pd.notnull(min_date) else '2023-01-01'
    fx_dict, fx_fallback = get_historical_fx(start_str)
    gbpusd_rate = float(fx_dict['GBPUSD=X'].iloc[-1])
    gbpeur_rate = float(fx_dict['GBPEUR=X'].iloc[-1])

    grouped['Market Value GBP'] = grouped.apply(lambda r: convert_to_gbp(r, gbpusd_rate, gbpeur_rate), axis=1)
    grouped['PandL GBP'] = grouped['Market Value GBP'] + grouped['Costs']

    total_market_value_gbp = float(grouped['Market Value GBP'].sum())
    usd_val = float(grouped[grouped['Currency'] == 'USD']['Market Value GBP'].sum())
    eur_val = float(grouped[grouped['Currency'] == 'EUR']['Market Value GBP'].sum())
    gbp_val = float(grouped[grouped['Currency'] == 'GBP']['Market Value GBP'].sum())
    total_costs = float(grouped['Costs'].sum())

    positions_list = []
    for ticker, row in grouped.iterrows():
        positions_list.append({
            "ticker": str(ticker),
            "market": str(row['Market']),
            "quantity": float(row['Quantity']),
            "current_price": float(row['Current Price']),
            "market_value_gbp": float(row['Market Value GBP']),
            "pnl_gbp": float(row['PandL GBP']),
            "currency": str(row['Currency'])
        })

    return {
        "total_market_value_gbp": total_market_value_gbp,
        "total_invested_cash": abs(total_costs),
        "total_pnl_gbp": float(grouped['PandL GBP'].sum()),
        "currency_allocation": {
            "usd_gbp": usd_val,
            "eur_gbp": eur_val,
            "gbp": gbp_val,
            "total_gbp": total_market_value_gbp
        },
        "positions": positions_list,
        "unresolved_symbols": unresolved_symbols,
        "excluded_row_count": excluded_row_count,
        "data_quality": {
            "degraded": bool(unpriced) or fx_fallback,
            "fx_fallback": fx_fallback,
            "unpriced_tickers": unpriced,
            "failures": price_failures,
        },
    }

def _classify_blank_summary(market_name: Any) -> str:
    """IG leaves `Summary` blank for interest, some fees and some deposits; recover them from MarketName."""
    name = str(market_name) if pd.notnull(market_name) else ''
    if 'Cash Interest' in name:
        return 'Cash Interest'
    if 'Section 31 Fee' in name:
        return 'Section 31 Fee'
    if 'Custody Fee' in name:
        return 'Custody Fee'
    if name.startswith('Bank Deposit') or name.startswith('Card payment'):
        return 'Cash In'
    return 'Uncategorised'

def _cash_amounts(column: pd.Series) -> pd.Series:
    """IG's `PL Amount` column as floats, NaN where a cell will not parse.

    Strips thousands separators regardless of dtype: pandas 3 reads this column as StringDtype,
    not object, and "5,000.00" would otherwise coerce to NaN.
    """
    return pd.to_numeric(
        column.astype(str).str.replace(r'[£,\s]', '', regex=True), errors='coerce'
    )

def calculate_cashflow_waterfall(df_transactions: pd.DataFrame) -> List[Dict[str, Any]]:
    df = df_transactions.copy()
    df['PL Amount'] = _cash_amounts(df['PL Amount']).fillna(0)
    blank = df['Summary'].isna() | (df['Summary'].astype(str).str.strip() == '')
    market_names = df['MarketName'] if 'MarketName' in df.columns else pd.Series('', index=df.index)
    df['Summary'] = df['Summary'].astype(object)
    df.loc[blank, 'Summary'] = market_names[blank].map(_classify_blank_summary)

    summary_flow = df.groupby('Summary')['PL Amount'].sum().to_dict()
    waterfall = []
    for cat, val in summary_flow.items():
        waterfall.append({"category": str(cat), "amount": float(val)})
    return waterfall

# Why a derived balance was withheld. Every one of these has to beat showing a figure, because a
# wrong balance is indistinguishable from a right one on screen.
CASH_WITHHELD_NO_LEDGER = "no_ledger"
CASH_WITHHELD_UNREADABLE = "unreadable_amounts"
CASH_WITHHELD_NON_GBP = "non_gbp"
CASH_WITHHELD_UNDATED = "undated"
CASH_WITHHELD_PARTIAL_WINDOW = "partial_window"

# `DateUtc` is ISO and unambiguous, so it is preferred; `TextDate` is `DD/MM/YY`, which has to be
# read day-first or 01/04/19 becomes 4 January. Both formats are pinned rather than inferred: a
# layout we do not recognise should leave the balance withheld, not reordered by a dateutil guess.
_STATEMENT_DATE_COLUMNS = (("DateUtc", "ISO8601"), ("TextDate", "%d/%m/%y"))

def _statement_dates(df: pd.DataFrame) -> Optional[pd.Series]:
    """Timestamps for every row, or None if no column dates all of them.

    A column that dates only some rows is no use here: the rows it misses are cash movements
    missing from the coverage check, which is the one thing standing between a partial export
    and a wrong balance.
    """
    for column, date_format in _STATEMENT_DATE_COLUMNS:
        if column not in df.columns:
            continue
        parsed = pd.to_datetime(df[column], errors='coerce', format=date_format)
        if parsed.notna().all():
            return parsed
    return None

def derive_cash_balance(df_transactions: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """Settled cash balance implied by an IG transaction statement, or why it cannot be derived.

    `PL Amount` is already signed -- deposits arrive positive and fees negative without needing a
    flip from `Transaction type` -- so the balance is just its sum. That only holds if the
    statement reaches account inception: a mid-life export omits the founding deposits and nets
    to a figure that still looks like a balance.

    Which is detectable without trusting the filename. On a complete ledger the running balance
    never goes negative, because nothing can be bought before the cash to buy it arrives. The
    check runs on daily totals rather than row order, since rows within one day carry no sequence
    and a purchase booked ahead of its deposit would dip the balance spuriously.

    This is not a broker figure. IG's own "available to trade" nets margin and unsettled trades,
    and there is no IG balance client in this repo -- the statement is the only source.
    """
    if (
        df_transactions is None
        or df_transactions.empty
        or 'PL Amount' not in df_transactions.columns
    ):
        return {"withheld_reason": CASH_WITHHELD_NO_LEDGER}

    amounts = _cash_amounts(df_transactions['PL Amount'])
    if amounts.isna().any():
        # Unlike the waterfall, a balance cannot absorb these as zero: the sum would be wrong by
        # an unknown amount and nothing on screen would say so.
        return {"withheld_reason": CASH_WITHHELD_UNREADABLE}

    currencies = df_transactions.get('CurrencyIsoCode')
    if currencies is None or set(currencies.astype(str).str.strip().str.upper()) != {'GBP'}:
        # A bare sum is only a balance while every row is in one currency, and the statement has
        # no rate to convert with.
        return {"withheld_reason": CASH_WITHHELD_NON_GBP}

    dates = _statement_dates(df_transactions)
    if dates is None:
        return {"withheld_reason": CASH_WITHHELD_UNDATED}

    covered = {
        "covered_from": dates.min().strftime('%Y-%m-%d'),
        "covered_to": dates.max().strftime('%Y-%m-%d'),
    }
    running = amounts.groupby(dates.dt.normalize()).sum().sort_index().cumsum()
    if (running.round(2) < 0).any():
        return {**covered, "withheld_reason": CASH_WITHHELD_PARTIAL_WINDOW}

    return {**covered, "balance_gbp": round(float(amounts.sum()), 2)}


# The one `Summary` category where money crosses the account boundary. Everything else in the
# statement -- `Client Consideration`, `Dividend`, `Share Dealing Commissions`, `SDRT`, cash
# interest -- moves cash that is already inside the account. Matching an index against those would
# buy it with money the owner never paid in, and would double-count every dividend.
EXTERNAL_CASH_SUMMARY = 'Cash In'

def external_cashflows(df_transactions: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """Dated deposits and withdrawals from an IG transaction statement, or why they cannot be read.

    This answers "when did new money arrive, and how much", which is what a benchmark needs to
    compare like with like: a portfolio fed by years of deposits cannot be measured against a
    single lump sum invested on day one.

    Gated on `derive_cash_balance` so a statement that cannot be trusted yields no cashflows at
    all. Its partial-export check matters more here than it does for a balance. A mid-life export
    omits the founding deposits, and understating deposits makes the index look beaten by whatever
    is missing -- an error biased towards flattering the portfolio, which is the kind least likely
    to be questioned.

    Amounts are returned signed, as the statement writes them, so a withdrawal sells units back.
    """
    balance = derive_cash_balance(df_transactions)
    if 'withheld_reason' in balance:
        return {"withheld_reason": balance['withheld_reason']}

    if 'Summary' not in df_transactions.columns:
        # Deposits are identified by `Summary`; without it every row is indistinguishable from a
        # trade. That is not a statement this can read, rather than a statement with no deposits.
        return {"withheld_reason": CASH_WITHHELD_NO_LEDGER}

    # Safe to use unguarded: derive_cash_balance returned a balance, so every amount parsed and
    # every row is dated.
    amounts = _cash_amounts(df_transactions['PL Amount'])
    dates = _statement_dates(df_transactions)

    summaries = df_transactions['Summary']
    blank = summaries.isna() | (summaries.astype(str).str.strip() == '')
    market_names = (
        df_transactions['MarketName']
        if 'MarketName' in df_transactions.columns
        else pd.Series('', index=df_transactions.index)
    )
    resolved = summaries.astype(object).copy()
    resolved.loc[blank] = market_names[blank].map(_classify_blank_summary)

    # IG leaves `Summary` blank on some deposits, so the recovery above is not cosmetic: on the
    # reference statement it moves one `Bank Deposit` row worth GBP 24,633 into this selection,
    # a quarter of the GBP 94,633 total.
    external = resolved.astype(str).str.strip() == EXTERNAL_CASH_SUMMARY
    flows = [
        {"date": date.strftime('%Y-%m-%d'), "amount_gbp": round(float(amount), 2)}
        for date, amount in zip(dates[external], amounts[external])
        if round(float(amount), 2) != 0
    ]
    flows.sort(key=lambda flow: flow['date'])

    return {
        "cashflows": flows,
        "total_gbp": round(sum(flow['amount_gbp'] for flow in flows), 2),
        "covered_from": balance['covered_from'],
        "covered_to": balance['covered_to'],
    }

