import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from backend.app.services.market_service import get_current_prices, get_historical_fx
from backend.app.services.ticker_service import load_ticker_mappings
from backend.app.core.config import settings

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

    df['Ticker'] = df['Market'].map(ticker_map)
    df_valid = df[df['Ticker'].notnull()].copy()

    if df_valid.empty:
        return {
            "total_market_value_gbp": 0.0,
            "total_invested_cash": 0.0,
            "total_pnl_gbp": 0.0,
            "currency_allocation": {"usd_gbp": 0.0, "eur_gbp": 0.0, "gbp": 0.0, "total_gbp": 0.0},
            "positions": []
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
    current_prices = get_current_prices(grouped.index.tolist())
    grouped['Current Price'] = grouped.index.map(current_prices)
    grouped['Quantity'] = pd.to_numeric(grouped['Quantity'], errors='coerce')
    grouped['Current Price'] = pd.to_numeric(grouped['Current Price'], errors='coerce').fillna(0)
    grouped['Market Value'] = grouped['Quantity'] * grouped['Current Price']

    # FX conversion
    min_date = df_valid['Date'].min() if 'Date' in df_valid.columns else datetime.now() - timedelta(days=365)
    start_str = min_date.strftime('%Y-%m-%d') if pd.notnull(min_date) else '2023-01-01'
    fx_dict = get_historical_fx(start_str)
    gbpusd_rate = float(fx_dict['GBPUSD=X'].iloc[-1]) if 'GBPUSD=X' in fx_dict and not fx_dict['GBPUSD=X'].empty else 1.25
    gbpeur_rate = float(fx_dict['GBPEUR=X'].iloc[-1]) if 'GBPEUR=X' in fx_dict and not fx_dict['GBPEUR=X'].empty else 1.15

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
        "positions": positions_list
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

