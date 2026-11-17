import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from backend.app.services.market_service import get_current_prices, get_historical_fx
from backend.app.services.ticker_service import load_ticker_mappings, resolve_ticker, find_unresolved_symbols
from backend.app.core.config import settings

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
        print(
            f"No price from any provider for {len(unpriced)} ticker(s): {', '.join(unpriced)}. "
            "Market value, P&L and totals are understated."
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

def calculate_cashflow_waterfall(df_transactions: pd.DataFrame) -> List[Dict[str, Any]]:
    df = df_transactions.copy()
    if 'PL Amount' in df.columns and df['PL Amount'].dtype == object:
        df['PL Amount'] = df['PL Amount'].astype(str).str.replace(',', '')
    df['PL Amount'] = pd.to_numeric(df['PL Amount'], errors='coerce').fillna(0)
    df['Summary'] = df['Summary'].fillna('Cash Interest - Platform Cost')

    summary_flow = df.groupby('Summary')['PL Amount'].sum().to_dict()
    waterfall = []
    for cat, val in summary_flow.items():
        waterfall.append({"category": str(cat), "amount": float(val)})
    return waterfall

