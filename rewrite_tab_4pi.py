import pandas as pd
import streamlit as st
import numpy as np
import json
import os
import time
from datetime import datetime, timedelta
from rewrite_ticker_resolution import use_sec_site
from getEODprice import getEODpriceUK, getEODpriceUSA
import rewrite_plot_portfolio_weights as ppw # TODO: rename to make it more intuitive
from market_data_api import OHLC_YahooFinance, HistoricalMarketData
import glob, socket, platform

from trading212.t212dec import lss
from trading212_api import Trading212API




@st.cache_data
def get_current_price(tickers: list) -> dict:
    eu_tickers = [ticker for ticker in tickers if ticker.endswith('.L') or ticker.endswith('.DE')]
    us_tickers = [ticker for ticker in tickers if '.' not in ticker]
    us_tickers_positions = getEODpriceUSA(us_tickers)
    eu_tickers_positions = getEODpriceUK(eu_tickers)
    return {**us_tickers_positions, **eu_tickers_positions}

def convert_to_gbp(row):
    if row.name.endswith('.L'):
        return row['Market Value']  # already in GBP
    elif row.name.endswith('.DE'):
        eur_to_gbp = GBPEUR.iloc[-1]
        return row['Market Value'] / eur_to_gbp  # convert EUR to GBP
    else:
        usd_to_gbp = GBPUSD.iloc[-1]
        return row['Market Value'] / usd_to_gbp  # convert USD to GBP

def color_green_red(val):
    color = 'green' if val > 0 else 'red'
    return f'background-color: {color}'


def calculate_past_date(period: str) -> datetime:
    """Calculate a past date based on period string, adjusted to business day."""
    PERIOD_DAYS = {'1y': 365, '6m': 182, '3m': 91, '1m': 30, '1w': 7, '1d': 1}

    if period not in PERIOD_DAYS:
        raise ValueError(f"Invalid period '{period}'. Use: {', '.join(PERIOD_DAYS.keys())}")
    
    past_date = datetime.today() - timedelta(days=PERIOD_DAYS[period])
    
    # Adjust weekend to preceding Friday
    weekend_offset = {5: 1, 6: 2}.get(past_date.weekday(), 0)
    return past_date - timedelta(days=weekend_offset)

@st.cache_data(ttl=3600, show_spinner=True)
def get_cached_t212_all_orders(api_key, api_secret):
    client = Trading212API(api_key=api_key, api_secret=api_secret)
    return fetch_all_paginated(client.get_historical_orders, label="all orders", delay=10.0)

@st.cache_data
def get_historical_fx(start_date: str):
    fx_data ={}
    for pair in ['GBPUSD=X', 'GBPEUR=X']:
        try:
            data = OHLC_YahooFinance(pair, start_date).yahooDataV8()
            # Convert index to datetime64[ns] to ensure compatibility with asof() lookup
            data.index = pd.to_datetime(data.index)
            fx_data[pair] = data['close']
        except Exception as e:
            print(f"Error retrieving data for {pair}: {e}")
    return fx_data


def calculate_benchmark_value(df_ohlc: pd.DataFrame, df_cash_in: pd.DataFrame) -> pd.DataFrame:
    """Simulate buying an index with each cash deposit and track the value over time.

    For each cash-in event, we buy units of the index at the next available
    trading day's close price (date + 1). Then for every subsequent trading day,
    the benchmark portfolio value = cumulative_units * close_price.

    Args:
        df_ohlc: OHLC DataFrame from yahooDataV8() with columns ['Date', 'close']
        df_cash_in: DataFrame with columns ['TextDate', 'PL Amount']

    Returns:
        DataFrame with columns ['Date', 'Value'] or empty DataFrame if no data
    """
    df_b = df_ohlc.reset_index(drop=True).copy()
    df_b['Date'] = pd.to_datetime(df_b['Date'])
    df_b = df_b.sort_values('Date').reset_index(drop=True)
    if df_b.empty:
        return pd.DataFrame(columns=['Date', 'Value'])

    cash_events = df_cash_in[['TextDate', 'PL Amount']].copy()
    cash_events['TextDate'] = pd.to_datetime(cash_events['TextDate'])
    cash_events = cash_events.sort_values('TextDate')

    # For each cash-in, find the next trading day and calculate units bought
    units_schedule = []  # list of (effective_date, units)
    for _, row in cash_events.iterrows():
        deposit_date = row['TextDate']
        amount = row['PL Amount']
        if amount <= 0:
            continue
        next_day = deposit_date + pd.Timedelta(days=1)
        eligible = df_b[df_b['Date'] >= next_day]
        if eligible.empty:
            continue
        buy_price = eligible.iloc[0]['close']
        if buy_price and buy_price > 0:
            units = amount / buy_price
            units_schedule.append((eligible.iloc[0]['Date'], units))

    if not units_schedule:
        return pd.DataFrame(columns=['Date', 'Value'])

    # Build daily benchmark portfolio value
    units_schedule.sort(key=lambda x: x[0])
    benchmark_values = []
    cumulative_units = 0.0
    schedule_idx = 0

    for _, brow in df_b.iterrows():
        date = brow['Date']
        close = brow['close']
        while schedule_idx < len(units_schedule) and units_schedule[schedule_idx][0] <= date:
            cumulative_units += units_schedule[schedule_idx][1]
            schedule_idx += 1
        if cumulative_units > 0 and close is not None and not np.isnan(close):
            benchmark_values.append({'Date': date, 'Value': cumulative_units * close})

    return pd.DataFrame(benchmark_values) if benchmark_values else pd.DataFrame(columns=['Date', 'Value'])



# copilot generated code for ticker holding period
def symbol_trading_summary(df_trade_history):
    df = df_trade_history.copy()
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce', dayfirst=True)
    df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(0)

    g = df.groupby('Ticker')
    first_date = g['Date'].min()
    last_appearance = g['Date'].max()
    current_qty = g['Quantity'].sum()

    out = pd.DataFrame({
        'Ticker': first_date.index,
        'FirstBuyDate': pd.to_datetime(first_date).dt.date,
        'CurrentQuantity': current_qty.values,
        'LastDate': pd.to_datetime(last_appearance).dt.date
    }).reset_index(drop=True)

    # If still held (non-zero quantity) set LastDate to None
    out.loc[out['CurrentQuantity'] != 0, 'LastDate'] = None

    return out

@st.cache_data
def historical_market_data_yahoo(market_data_collections: pd.DataFrame, df_trade_history: pd.DataFrame) -> pd.DataFrame:
    """Fetch historical market data from Yahoo Finance, with synthetic fallback for unavailable tickers.
    
    TODO: maintain a csv with historical market data and fx data, and update it when the app is run
    """
    return HistoricalMarketData(market_data_collections, df_trade_history).fetch_all()


def calculate_portfolio_value_on_date(
    target_date: datetime,
    df_trade_history: pd.DataFrame,
    df_market_historical_data: pd.DataFrame,
    fx_rates: dict  # {'GBPUSD': pd.Series, 'GBPEUR': pd.Series}
) -> float:
    """Calculate total portfolio value in GBP for a specific date.
    
    Args:
        target_date: The date to calculate portfolio value for
        df_trade_history: Trade history with columns ['Date', 'Ticker', 'Quantity', 'Currency']
        df_market_historical_data: Historical OHLC data with columns ['Date', 'Ticker', 'close']
        fx_rates: Dict with 'GBPUSD' and 'GBPEUR' as pd.Series with date index
    
    Returns:
        Total portfolio value in GBP as float
    """
    # Calculate positions on the target date
    df_trades_until_date = df_trade_history[df_trade_history['Date'] <= target_date]
    df_positions = df_trades_until_date.groupby('Ticker').agg({'Quantity': 'sum', 'Currency': 'last'})
    df_positions = df_positions[df_positions['Quantity'] != 0]
    
    if df_positions.empty:
        return 0.0
    
    if 'Ticker' not in df_positions.columns:
        df_positions = df_positions.reset_index()
    
    # Filter market data for target date
    target_date_normalized = pd.Timestamp(target_date).date()
    df_market_on_date = df_market_historical_data[
        df_market_historical_data['Date'] == target_date_normalized
    ].copy()
    
    # Merge positions with market data
    df_positions = pd.merge(df_positions, df_market_on_date, on='Ticker', how='left')
    
    # Get FX rates for the date
    usd_rate = fx_rates['GBPUSD'].asof(target_date)
    eur_rate = fx_rates['GBPEUR'].asof(target_date)
    
    # Calculate GBP value for each position
    df_positions['GBP_Value'] = 0.0
    df_positions.loc[df_positions['Currency'] == 'USD', 'GBP_Value'] = (
        df_positions['Quantity'] / usd_rate * df_positions['close']
    )
    df_positions.loc[df_positions['Currency'] == 'EUR', 'GBP_Value'] = (
        df_positions['Quantity'] / eur_rate * df_positions['close']
    )
    df_positions.loc[df_positions['Currency'] == 'GBP', 'GBP_Value'] = (
        df_positions['Quantity'] * df_positions['close'] / 100  # pence to pounds
    )
    
    return df_positions['GBP_Value'].sum()


def get_portfolio_value_history(
    account_id: str,
    df_trade_history: pd.DataFrame,
    df_market_historical_data: pd.DataFrame,
    fx_rates: dict,
    cache_file: str = 'user_portfolio_values.json'
) -> dict:
    """Get or compute historical portfolio values for all trading days.
    
    Caches results to JSON file keyed by account_id. Only computes values for
    dates not already in the cache.
    
    Args:
        account_id: Unique identifier for the account (e.g., 'QX2B3')
        df_trade_history: Trade history DataFrame
        df_market_historical_data: Historical OHLC data with 'Date' column
        fx_rates: Dict with 'GBPUSD' and 'GBPEUR' as pd.Series
        cache_file: Path to the JSON cache file
    
    Returns:
        Dict with date strings as keys and GBP values as values
    """
    pwd = os.path.dirname(os.path.realpath(__file__))
    cache_path = os.path.join(pwd, cache_file)
    
    # Load existing cache or create empty structure
    if os.path.exists(cache_path):
        with open(cache_path, 'r') as f:
            all_accounts_cache = json.load(f)
    else:
        all_accounts_cache = {}
    
    # Get or create cache for this account
    account_cache = all_accounts_cache.get(account_id, {})
    
    # Filter to only include dates where at least one US ticker has real data.
    # We identify real data by checking if 'high' is not NaN (synthetic data has NaN high).
    is_us_ticker = ~df_market_historical_data['Ticker'].str.contains(r'\.', na=False)
    has_real_data = df_market_historical_data['high'].notnull()
    trading_days = df_market_historical_data[is_us_ticker & has_real_data]['Date'].unique()
    
    # Find dates that need calculation (not already cached)
    cached_dates = set(account_cache.keys())
    dates_to_calculate = [d for d in trading_days if str(d) not in cached_dates]
    
    # Calculate values for missing dates
    if dates_to_calculate:
        print(f"Calculating portfolio values for {len(dates_to_calculate)} new dates...")
        for date in dates_to_calculate:
            # Convert to datetime for the calculation function
            target_date = pd.Timestamp(date)
            value = calculate_portfolio_value_on_date(
                target_date=target_date,
                df_trade_history=df_trade_history,
                df_market_historical_data=df_market_historical_data,
                fx_rates=fx_rates
            )
            account_cache[str(date)] = value
        
        # Save updated cache
        all_accounts_cache[account_id] = account_cache
        with open(cache_path, 'w') as f:
            json.dump(all_accounts_cache, f, indent=2)
        print(f"Saved portfolio values to {cache_path}")
    
    return account_cache



# ─── Helper: paginate through all Trading212 API results ─────────────────────────
def fetch_all_paginated(api_func, label="data", delay=1.0, **kwargs):
    """Fetch all items from a paginated Trading 212 API endpoint."""
    all_items = []
    cursor = None
    page = 1
    while True:
        status_msg = st.empty()
        status_msg.info(f"Fetching {label}... (Page {page}, {len(all_items)} items so far)")
        
        if cursor is not None:
            result = api_func(cursor=cursor, limit=50, **kwargs)
        else:
            result = api_func(limit=50, **kwargs)
            
        items = result.get("items", [])
        all_items.extend(items)
        next_page = result.get("nextPagePath")
        
        if not next_page or not items:
            status_msg.empty()
            break
            
        # Extract cursor from nextPagePath query params
        from urllib.parse import urlparse, parse_qs
        parsed = parse_qs(urlparse(next_page).query)
        cursor = parsed.get("cursor", [None])[0]
        page += 1
        
        # Respect rate limits
        if delay > 0:
            time.sleep(delay)
            
    return all_items



# --- Pi / local mode detection: if running on specific Pi + IP, skip uploader and read from ~/Downloads
def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None




st.title("Portfolio Management Dashboard and Analytics")

st.header("Upload Trade/Transaction History")
uploaded_file = st.file_uploader('''\
Upload your trade/transaction history in CSV format. Filename must be in the format of: \n
1. trade file must have filename start with Trade*.csv \n
2. transaction file must have filename start with Transaction*.csv''', type=["csv"], accept_multiple_files=True)


_is_pi_mode = False
try:
    uname = platform.uname()
    local_ip_addr = _local_ip()
    if (('pi' in uname.node.lower() or 'rasp' in uname.node.lower()) and
        ('6.12.47+rpt-rpi-v8' in uname.release) and
        (local_ip_addr == '192.168.1.201')):
        _is_pi_mode = True
except Exception:
    _is_pi_mode = False

# Build the list of files to process: uploaded files OR local downloads when on Pi
files_to_process = []
if uploaded_file is not None:
    files_to_process.extend(uploaded_file)

if _is_pi_mode:
    downloads_dir = os.path.expanduser('~/Downloads')
    trade_files = sorted(glob.glob(os.path.join(downloads_dir, 'Trade*.csv')))
    trans_files = sorted(glob.glob(os.path.join(downloads_dir, 'Transaction*.csv')))
    # Only use the most recent Trade and Transaction files to avoid
    # duplicate sections and StreamlitDuplicateElementId errors
    if trade_files:
        files_to_process.append(trade_files[-1])
    if trans_files:
        files_to_process.append(trans_files[-1])

if files_to_process:
    for f in files_to_process:
        is_string_path = isinstance(f, str)
        if (is_string_path and os.path.basename(f).startswith("Trade") and f.endswith(".csv")) or (not is_string_path and f.name.startswith("Trade") and f.name.endswith(".csv")):
            # Extract account identifier from filename (e.g., 'QX2B3' from 'TradeHistory-QX2B3-(...).csv')
            if is_string_path:
                fname = os.path.basename(f)
                filename_parts = fname.split('-')
                account_id = filename_parts[1] if len(filename_parts) > 1 else 'default'
                df_trade_history = pd.read_csv(f)
            else:
                filename_parts = f.name.split('-')
                account_id = filename_parts[1] if len(filename_parts) > 1 else 'default'
                df_trade_history = pd.read_csv(f)
            df_trade_history['Date'] = pd.to_datetime(df_trade_history['TextDate'], errors='coerce', dayfirst=True)
            
            # add ticker to trade history table
            pwd = os.path.dirname(os.path.realpath(__file__))
            reference_data_json_file = pwd + '/company_name_to_ticker.json'
            with open(reference_data_json_file, 'r') as json_file: # TODO: move this to a database instead
                company_name_to_ticker = json.load(json_file)
            df_trade_history['Ticker'] = df_trade_history['Market'].map(company_name_to_ticker)
            
            ## find missing symbols
            missing_symbols = df_trade_history[~df_trade_history['Market'].isin(company_name_to_ticker.keys())]['Market'].unique()
            if len(missing_symbols) > 0:
                print("The following company names are not recognized and have no Ticker assigned:")
                for symbol in missing_symbols:
                    print(f"• {symbol}") 
                print("Attempting to resolve missing company names using SEC data...")
                resolved_symbols = use_sec_site(missing_symbols.tolist())
                # compare resolved_symbols with missing_symbols, if there is still missing, add them as None to allow user to add them manually
                if len(missing_symbols) != len(resolved_symbols): # TODO: find another way to resolve symbols
                    for ms in missing_symbols:
                        if ms not in resolved_symbols:
                            resolved_symbols[ms] = None
                st.write(f"Resolved Symbols: {resolved_symbols}")
                st.write(f"unresolved Symbols: {[k for k,v in resolved_symbols.items() if v is None]}")

                # Allow user to edit resolved symbols
                st.subheader("Review and edit resolved mappings:")
                edited_symbols = {}
                
                for market_name, ticker in resolved_symbols.items():
                    col1, col2, col3 = st.columns([2, 2, 1])
                    col1.write(f"**{market_name}**")
                    # User can edit the ticker in text_input
                    edited_ticker = col2.text_input(
                        label="Ticker",
                        value=ticker if ticker else "",
                        key=f"ticker_{market_name}",
                        label_visibility="collapsed"
                    )
                    edited_symbols[market_name] = edited_ticker
                    # Checkbox to confirm inclusion
                    if col3.checkbox("✓ Include", key=f"include_{market_name}", value=True):
                        pass  # will be saved if checked
                
                # Save confirmed mappings
                col_save, col_cancel = st.columns(2)
                if col_save.button("✅ Save to company_name_to_ticker.json"):
                    # Filter: only save if checkbox is checked AND ticker is not empty
                    confirmed_mappings = {
                        market_name: ticker 
                        for market_name, ticker in edited_symbols.items() 
                        if ticker.strip() and st.session_state.get(f"include_{market_name}", False)
                    }
                    
                    if confirmed_mappings:
                        company_name_to_ticker.update(confirmed_mappings)
                        with open(reference_data_json_file, 'w') as json_file:
                            json.dump(company_name_to_ticker, json_file, indent=2)
                        st.success(f"✅ Saved {len(confirmed_mappings)} new mappings!")
                        st.rerun()
                        # check if trade history dataframe has no missing tickers now
                        if df_trade_history['Ticker'].isnull().any():
                            st.write("There are still unresolved tickers in trade history:")
                            st.table(df_trade_history[df_trade_history['Ticker'].isnull()])
                    else:
                        st.error("No valid mappings to save (empty tickers or unchecked items).")
                
                if col_cancel.button("❌ Cancel"):
                    st.info("Cancelled. No changes made.")




            
            # print trade history this quarter
            st.subheader("Trade History This Quarter")
            today = datetime.now()
            current_quarter = pd.Period(today, freq='Q')
            current_quarter_trade_history = df_trade_history[(df_trade_history['Date'].dt.to_period('Q') == current_quarter) & (df_trade_history['Activity']=="TRADE")] # type: ignore[attr-defined]
            st.dataframe(current_quarter_trade_history)


            # remove df_trade_history row that Ticker is null
            df_trade_history_not_null = df_trade_history[df_trade_history['Ticker'].notnull()]
            if len(df_trade_history_not_null) != len(df_trade_history):
                st.warning(f"⚠️ {len(df_trade_history) - len(df_trade_history_not_null)} rows with unresolved Ticker were excluded from analysis.Result might not be accurate.")
            
            # update ticker
            df_trade_history_ticker_updated = df_trade_history_not_null.copy()
            df_trade_history_ticker_updated['Ticker'] = df_trade_history_ticker_updated['Ticker'].replace(company_name_to_ticker)

            # calculate current positions
            df_current_positions = df_trade_history_ticker_updated.groupby('Ticker').agg({'Quantity':'sum', 'Market': 'last', 'Cost/Proceeds': 'sum', 'Charges': 'sum', 'Commission': 'sum', 'Currency': 'last'})
            df_current_positions = df_current_positions[df_current_positions['Quantity'] != 0]
            df_current_positions['Costs'] = df_current_positions['Cost/Proceeds'] + df_current_positions['Charges'] + df_current_positions['Commission']
            current_prices = get_current_price(df_current_positions.index.tolist())
            df_current_positions['Current Price'] = df_current_positions.index.map(current_prices) # add EOD price to current price TODO: change when market open
            df_current_positions['Quantity'] = pd.to_numeric(df_current_positions['Quantity'], errors='coerce')
            df_current_positions['Current Price'] = pd.to_numeric(df_current_positions['Current Price'], errors='coerce')
            df_current_positions['Market Value'] = df_current_positions['Quantity'] * df_current_positions['Current Price']
            GBPUSD = get_historical_fx(df_trade_history_ticker_updated['Date'].min().strftime('%Y-%m-%d'))['GBPUSD=X']
            GBPEUR = get_historical_fx(df_trade_history_ticker_updated['Date'].min().strftime('%Y-%m-%d'))['GBPEUR=X']
            df_current_positions['Market Value GBP'] = df_current_positions.apply(convert_to_gbp, axis=1)

            Total_market_value_gbp = df_current_positions['Market Value GBP'].sum()
            USD_market_value_in_gbp = df_current_positions[df_current_positions['Currency']=='USD']['Market Value GBP'].sum()
            EUR_market_value_in_gbp = df_current_positions[df_current_positions['Currency']=='EUR']['Market Value GBP'].sum()
            GBP_market_value_in_gbp = df_current_positions[df_current_positions['Currency']=='GBP']['Market Value GBP'].sum()
            
            st.plotly_chart(ppw.pie_chart_equity_by_currency(USD_market_value_in_gbp, EUR_market_value_in_gbp, GBP_market_value_in_gbp, Total_market_value_gbp))
            df_current_positions['PandL GBP'] = df_current_positions['Market Value GBP'] + df_current_positions['Costs']
            df_present_positions = df_current_positions[['Market', 'Quantity', 'Current Price', 'Market Value GBP', 'PandL GBP']]
            st.dataframe(df_present_positions.style.format({
                'Market Value GBP': '£{:,.2f}',
                'PandL GBP': '£{:,.2f}'
            }).map(color_green_red, subset=['PandL GBP']), height=800)

            
            # single ticker trade history section
            trade_history_search_options1 = df_trade_history_ticker_updated['Market'].unique()
            trade_history_search_options2 = df_trade_history_ticker_updated['Ticker'].unique()
            trade_history_search_options = trade_history_search_options1.tolist() + trade_history_search_options2.tolist() 
            selected_company = st.selectbox(
                label="Select an instrument to see trade history",
                options=trade_history_search_options,
                key="select_company_ticker"
            )

            if selected_company in company_name_to_ticker.values():
                selected_ticker = selected_company
            else:
                selected_ticker = company_name_to_ticker[selected_company]
                # check if the ticker itself is a key in the map (chained mapping)
                if selected_ticker in company_name_to_ticker:
                     selected_ticker = company_name_to_ticker[selected_ticker]
                print(selected_ticker)
    
            if selected_company:
                df_ticker_trade_history = df_trade_history_ticker_updated[
                    (df_trade_history_ticker_updated['Ticker'] == selected_ticker) & 
                    (df_trade_history_ticker_updated['Activity'] == "TRADE")
                ].sort_values(by='Date', ascending=False)
        
                st.subheader(f"Trade History for {selected_company} ({selected_ticker})")
                st.table(df_ticker_trade_history[['Market', 'Ticker', 'Date', 'Direction', 'Quantity','Price', 'Currency']])

                # ── Historical price chart with buy/sell markers ──
                try:
                    first_trade_date = df_ticker_trade_history['Date'].min()
                    start_date_str = first_trade_date.strftime('%Y-%m-%d')
                    df_ohlc = OHLC_YahooFinance(selected_ticker, start_date_str).yahooDataV8()
                    df_ohlc['Date'] = pd.to_datetime(df_ohlc['Date'])

                    # Prepare trade markers (ensure numeric Price & datetime Date)
                    df_trades_for_chart = df_ticker_trade_history[['Date', 'Direction', 'Price', 'Quantity']].copy()
                    df_trades_for_chart['Date'] = pd.to_datetime(df_trades_for_chart['Date'])
                    df_trades_for_chart['Price'] = pd.to_numeric(df_trades_for_chart['Price'], errors='coerce')
                    df_trades_for_chart['Quantity'] = pd.to_numeric(df_trades_for_chart['Quantity'], errors='coerce').abs()

                    # IG quotes prices in pence/cents and are NOT split-adjusted;
                    # Yahoo returns split-adjusted data in pounds/dollars.
                    # Per-trade normalisation: compare each trade's price to the nearest
                    # Yahoo close and divide by the rounded ratio. This simultaneously
                    # handles cents→dollars conversion AND stock-split discrepancies.
                    for idx, row in df_trades_for_chart.iterrows():
                        nearest_idx = (df_ohlc['Date'] - row['Date']).abs().idxmin()
                        nearest_close = df_ohlc.loc[nearest_idx, 'close']
                        if nearest_close > 0 and row['Price'] > 0:
                            ratio = row['Price'] / nearest_close
                            if ratio > 5:
                                df_trades_for_chart.at[idx, 'Price'] = row['Price'] / round(ratio)

                    trade_currency = df_ticker_trade_history['Currency'].iloc[0] if not df_ticker_trade_history.empty else ''
                    fig_ticker = ppw.ticker_price_chart_with_trades(
                        df_ohlc, df_trades_for_chart, selected_ticker, currency=trade_currency
                    )
                    st.plotly_chart(fig_ticker, use_container_width=True)
                except Exception as e:
                    st.warning(f"⚠️ Could not load market data chart for {selected_ticker}: {e}")




            # plot portfolio weights TODO: buggy, eg use any symbol highlight won't work
            standout = [0.0] * len(df_current_positions)  # selected instrument highlight
            instruments_list = df_current_positions['Market'].tolist()
            if selected_company in instruments_list:
                idx = instruments_list.index(selected_company)
                standout[idx] = 0.5
            current_GBP_rate = {'GBPUSD=X': GBPUSD.iloc[-1], 'GBPEUR=X': GBPEUR.iloc[-1]}
            fig = ppw.plot_portfolio_weights(df_current_positions, standout, current_GBP_rate)
            st.plotly_chart(fig, width="stretch")


            # ============ PORTFOLIO VALUE OVER TIME WIDGET ============
            st.subheader("Portfolio Value Over Time")
            
            # Get historical market data and FX rates for the chart
            market_data_collections = symbol_trading_summary(df_trade_history_not_null)
            df_market_historical_data = historical_market_data_yahoo(market_data_collections, df_trade_history_not_null)
            df_market_historical_data['Date'] = pd.to_datetime(df_market_historical_data['Date']).dt.date
            fx_rates = {'GBPUSD': GBPUSD, 'GBPEUR': GBPEUR}
            
            # Get cached or calculate portfolio value history
            portfolio_values_dict = get_portfolio_value_history(
                account_id=account_id,
                df_trade_history=df_trade_history_ticker_updated,
                df_market_historical_data=df_market_historical_data,
                fx_rates=fx_rates
            )
            
            # Convert to DataFrame for plotting
            df_portfolio_history = pd.DataFrame([
                {'Date': pd.to_datetime(date), 'Portfolio Value (GBP)': value}
                for date, value in portfolio_values_dict.items()
            ]).sort_values('Date')
            
            # --- Check for benchmarks from Transaction file if uploaded ---
            benchmark_values = {}
            df_cashIn_for_bench = None
            for tmp_f in files_to_process:
                is_tmp_string = isinstance(tmp_f, str)
                tmp_fname = os.path.basename(tmp_f) if is_tmp_string else tmp_f.name
                if tmp_fname.startswith("Transaction") and tmp_fname.endswith(".csv"):
                    tmp_df = pd.read_csv(tmp_f)
                    if not is_tmp_string:
                        tmp_f.seek(0)
                    tmp_df['Summary'] = tmp_df['Summary'].fillna('Cash Interest - Platform Cost')
                    tmp_df['PL Amount'] = tmp_df['PL Amount'].astype(str).str.replace(',', '')
                    type_dict = {'TextDate': 'datetime64[s]', 'PL Amount': 'float', 'Summary': 'category', 'Transaction type': 'category', 'Cash transaction': 'boolean', 'MarketName': 'string'}
                    tmp_df = tmp_df.astype(type_dict)
                    tmp_df.loc[tmp_df['MarketName'] == 'Bank Deposit', 'Summary'] = 'Cash In'
                    df_cashIn_for_bench = tmp_df[tmp_df['Summary'] == 'Cash In']
                    break
            
            if df_cashIn_for_bench is not None and not df_cashIn_for_bench.empty:
                st.write("Compare with benchmarks:")
                col_sp500, col_ndx = st.columns(2)
                show_sp500 = col_sp500.checkbox("S&P 500", value=False)
                show_ndx = col_ndx.checkbox("Nasdaq 100", value=False)
                
                benchmark_start = df_cashIn_for_bench['TextDate'].min().strftime('%Y-%m-%d')
                
                if show_sp500:
                    try:
                        sp500_ohlc = OHLC_YahooFinance("^SPX", benchmark_start).yahooDataV8()
                        benchmark_values['S&P 500'] = calculate_benchmark_value(sp500_ohlc, df_cashIn_for_bench)
                    except Exception as e:
                        st.warning(f"⚠️ Could not fetch S&P 500 data: {e}")
                
                if show_ndx:
                    try:
                        nasdaq100_ohlc = OHLC_YahooFinance("^NDX", benchmark_start).yahooDataV8()
                        benchmark_values['Nasdaq 100'] = calculate_benchmark_value(nasdaq100_ohlc, df_cashIn_for_bench)
                    except Exception as e:
                        st.warning(f"⚠️ Could not fetch Nasdaq 100 data: {e}")

            fig_portfolio = ppw.portfolio_value_over_time(df_portfolio_history, account_id, benchmark_values)
            st.plotly_chart(fig_portfolio, width="stretch")


            # Date Range Slider
            # today_date = datetime.now().date()
            # one_year_ago = today_date - pd.DateOffset(years=1)
            # two_years_ago = today_date - pd.DateOffset(years=2)

            # selected_date_range = st.slider(
            #     "Select Date Range",
            #     min_value=two_years_ago.date(),
            #     max_value=today_date,
            #     value=(one_year_ago.date(), today_date),
            #     format="YYYY-MM-DD"
            # )
            # start_date_selected, end_date_selected = selected_date_range
            # st.write(f"Showing data from {start_date_selected} to {end_date_selected}")
            


            selected_date = None
            st.write("Select a time period to view portfolio value on that date:")
            left1, left2, middle1, middle2, right1, right2 = st.columns(6)
            if left1.button("1y", width="stretch"):
                selected_date = calculate_past_date("1y")
            if left2.button("6m", width="stretch"):
                selected_date = calculate_past_date("6m")
            if middle1.button("3m", width="stretch"):
                selected_date = calculate_past_date("3m")
            if middle2.button("1m", width="stretch"):
                selected_date = calculate_past_date("1m")
            if right1.button("1w", width="stretch"):
                selected_date = calculate_past_date("1w")
            if right2.button("1d", width="stretch"):
                selected_date = calculate_past_date("1d")
            
            if selected_date:
                Total_value_in_GBP_selected_date = calculate_portfolio_value_on_date(
                target_date=selected_date,
                df_trade_history=df_trade_history_ticker_updated,
                df_market_historical_data=df_market_historical_data,
                fx_rates=fx_rates
                )
                
                diff = Total_market_value_gbp - Total_value_in_GBP_selected_date
                st.markdown(f"Total value in GBP on {selected_date.date()}: **£{Total_value_in_GBP_selected_date:,.2f}**, value today: **£{Total_market_value_gbp:,.2f}**")
                st.markdown(f"Value difference between {selected_date.date()} and today: **<span style='color:{'green' if diff > 0 else 'red'}'>£{diff:,.2f}</span>**", unsafe_allow_html=True)
        
        elif (isinstance(f, str) and os.path.basename(f).startswith("Transaction") and f.endswith(".csv")) or (not isinstance(f, str) and f.name.startswith("Transaction") and f.name.endswith(".csv")):
            if isinstance(f, str):
                df_transactions = pd.read_csv(f)
            else:
                df_transactions = pd.read_csv(f)
            df_transactions['Summary'] = df_transactions['Summary'].fillna('Cash Interest - Platform Cost')
            type_dict = {'TextDate': 'datetime64[s]', 'PL Amount': 'float', 'Summary': 'category', 'Transaction type': 'category', 'Cash transaction': 'boolean', 'MarketName': 'string'}
            df_transactions['PL Amount'] = df_transactions['PL Amount'].str.replace(',','')
            df_transactions = df_transactions.astype(type_dict)
            df_transactions.loc[df_transactions['MarketName'] == 'Bank Deposit', 'Summary'] = 'Cash In'
            df_cashIn = df_transactions[df_transactions['Summary']=='Cash In' ]
            st.metric(label="Total Cash Invested", value=f"£{df_cashIn['PL Amount'].sum():,.2f}")
            net_cashflow = {}
            for i in df_transactions['Summary'].unique():
                net_cashflow[i] = df_transactions[df_transactions['Summary'] == i]['PL Amount'].sum()
            st.write(net_cashflow)
            fig = ppw.plot_cashflow(net_cashflow)
            st.plotly_chart(fig, width="stretch")



# ═══════════════════════════════════════════════════════════════════════
# TRADING 212 PORTFOLIO ANALYSIS (API-driven)
# ═══════════════════════════════════════════════════════════════════════
st.divider()
st.header("📊 Trading 212 Portfolio Analysis")

t212_api_key, t212_api_secret = lss(st.text_input("Enter your passcode to unlock API keys: ", type="password", key="t212_api_secret_input"))


if t212_api_secret and t212_api_key:
    try:
        t212_client = Trading212API(api_key=t212_api_key, api_secret=t212_api_secret)

        # ============ ACCOUNT SUMMARY ============
        with st.spinner("Fetching account summary..."):
            account_summary = t212_client.get_account_summary()

        account_id = account_summary.get("id", "N/A")
        account_currency = account_summary.get("currency", "GBP")
        total_value = account_summary.get("totalValue", 0)
        cash_info = account_summary.get("cash", {})
        investments_info = account_summary.get("investments", {})

        st.subheader(f"Account Summary (ID: {account_id})")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Account Value", f"£{total_value:,.2f}")
        col2.metric("Cash Available", f"£{cash_info.get('availableToTrade', 0):,.2f}")
        col3.metric(
            "Investments Value",
            f"£{investments_info.get('currentValue', 0):,.2f}",
            delta=f"£{investments_info.get('unrealizedProfitLoss', 0):,.2f}"
        )

        col_cost, col_realised = st.columns(2)
        col_cost.metric("Total Cost Basis", f"£{investments_info.get('totalCost', 0):,.2f}")
        col_realised.metric("Realised P&L (All Time)", f"£{investments_info.get('realizedProfitLoss', 0):,.2f}")

        # ============ OPEN POSITIONS (from API - includes live prices) ============
        with st.spinner("Fetching open positions..."):
            positions_raw = t212_client.get_open_positions()

        if positions_raw:
            st.subheader("📈 Current Open Positions")

            rows = []
            for pos in positions_raw:
                instrument = pos.get("instrument", {})
                wallet = pos.get("walletImpact", {})
                rows.append({
                    "Ticker": instrument.get("ticker", ""),
                    "Name": instrument.get("name", ""),
                    "ISIN": instrument.get("isin", ""),
                    "Currency": instrument.get("currency", ""),
                    "Quantity": pos.get("quantity", 0),
                    "Avg Price Paid": pos.get("averagePricePaid", 0),
                    "Current Price": pos.get("currentPrice", 0),
                    "Total Cost (£)": wallet.get("totalCost", 0),
                    "Current Value (£)": wallet.get("currentValue", 0),
                    "Unrealised P&L (£)": wallet.get("unrealizedProfitLoss", 0),
                    "FX Impact (£)": wallet.get("fxImpact", 0),
                    "Opened": pos.get("createdAt", ""),
                })

            df_t212_positions = pd.DataFrame(rows)

            # Summary metrics
            t212_total_value = df_t212_positions["Current Value (£)"].sum()
            t212_total_cost = df_t212_positions["Total Cost (£)"].sum()
            t212_total_pnl = df_t212_positions["Unrealised P&L (£)"].sum()
            t212_total_fx = df_t212_positions["FX Impact (£)"].sum()

            col_val, col_pnl, col_fx = st.columns(3)
            col_val.metric("Positions Total Value", f"£{t212_total_value:,.2f}")
            col_pnl.metric("Unrealised P&L", f"£{t212_total_pnl:,.2f}",
                           delta=f"{t212_total_pnl/t212_total_cost*100:.1f}%" if t212_total_cost else "")
            col_fx.metric("FX Impact", f"£{t212_total_fx:,.2f}")

            # Portfolio weights pie chart
            st.plotly_chart(
                ppw.pie_chart_equity_by_currency(
                    df_t212_positions[df_t212_positions['Currency'] == 'USD']['Current Value (£)'].sum(),
                    df_t212_positions[df_t212_positions['Currency'] == 'EUR']['Current Value (£)'].sum(),
                    df_t212_positions[df_t212_positions['Currency'].isin(['GBP', 'GBX'])]['Current Value (£)'].sum(),
                    t212_total_value
                )
            )

            # Positions table
            st.dataframe(
                df_t212_positions[['Name', 'Quantity', 'Avg Price Paid', 'Current Price',
                                   'Currency', 'Current Value (£)', 'Unrealised P&L (£)', 'FX Impact (£)']]
                .style.format({
                    'Quantity': lambda x: f"{x:,.0f}" if x == int(x) else f"{x:,.4f}",
                    'Avg Price Paid': '{:,.4f}',
                    'Current Price': '{:,.2f}',
                    'Current Value (£)': '£{:,.2f}',
                    'Unrealised P&L (£)': '£{:,.2f}',
                    'FX Impact (£)': '£{:,.2f}',
                }).map(color_green_red, subset=['Unrealised P&L (£)', 'FX Impact (£)']),
            )
        else:
            st.info("No open positions found.")

        # ============ HISTORICAL ORDERS (Trade History) ============        
        st.subheader("🔎 Single Instrument Trade History")
        
        with st.spinner("Fetching historical order metadata to build dropdown... (may take a moment initially)"):
            all_orders = get_cached_t212_all_orders(t212_api_key, t212_api_secret)

        # Build options from all historically traded instruments
        t212_options = [""]
        if all_orders:
            traded_instruments = {}
            for item in all_orders:
                order = item.get("order", {})
                if order.get("status") == "FILLED":
                    tkr = order.get("ticker", "")
                    name = order.get("instrument", {}).get("name", "")
                    if tkr and name:
                        traded_instruments[tkr] = name
            
            # Sort by ticker name
            sorted_tickers = sorted(traded_instruments.items(), key=lambda x: x[0])
            t212_options += [f"{tkr}  —  {name}" for tkr, name in sorted_tickers]
            
        selected_t212 = st.selectbox("Select an instrument you have traded to view history:", options=t212_options, key="t212_api_instrument_select")
        manual_ticker = st.text_input("Or enter a Ticker directly (e.g., AAPL_US_EQ):", key="t212_manual_ticker")
        
        target_ticker = manual_ticker.strip().upper() if manual_ticker.strip() else (selected_t212.split("  —  ")[0] if selected_t212 else None)
        
        if target_ticker:
            # Efficiently filter from the already-fetched and cached all_orders
            instrument_orders = [
                item for item in all_orders 
                if item.get("order", {}).get("ticker") == target_ticker
            ]
            
            if instrument_orders:
                order_rows = []
                for item in instrument_orders:
                    order = item.get("order", {})
                    if order.get("status") != "FILLED":
                        continue
                    fill = item.get("fill", {})
                    instrument = order.get("instrument", {})
                    wallet = fill.get("walletImpact", {})
                    order_rows.append({
                        "Date": fill.get("filledAt", order.get("createdAt", "")),
                        "Side": order.get("side", ""),
                        "Type": order.get("type", ""),
                        "Ticker": order.get("ticker", ""),
                        "Name": instrument.get("name", ""),
                        "Quantity": order.get("filledQuantity", order.get("quantity", 0)),
                        "Price": fill.get("price", 0),
                        "Currency": order.get("currency", ""),
                        "Net Value (£)": wallet.get("netValue", 0),
                        "Realised P&L (£)": wallet.get("realisedProfitLoss", 0),
                        "FX Rate": wallet.get("fxRate", 0),
                        "Status": order.get("status", ""),
                        "Source": order.get("initiatedFrom", ""),
                    })

                df_t212_orders = pd.DataFrame(order_rows)
                df_t212_orders["Date"] = pd.to_datetime(df_t212_orders["Date"], errors="coerce")
                df_t212_orders.sort_values("Date", ascending=False, inplace=True)

                st.write(f"Loaded **{len(df_t212_orders)}** historical orders for **{target_ticker}**.")
                st.dataframe(
                    df_t212_orders[['Date', 'Side', 'Type', 'Name', 'Quantity', 'Price', 'Currency', 'Net Value (£)']]
                    .style.format({
                        'Quantity': lambda x: f"{x:,.0f}" if x == int(x) else f"{x:,.4f}",
                        'Price': '{:,.4f}',
                        'Net Value (£)': '£{:,.2f}',
                    })
                )
            else:
                st.info(f"No historical orders found for {target_ticker}.")
        else:
            st.info("Select or enter an instrument to load its trade history.")

        # ============ DIVIDENDS ============
        st.subheader("💸 Dividends")
        with st.spinner("Fetching dividends..."):
            all_dividends = fetch_all_paginated(t212_client.get_dividends, label="dividends", delay=10.0)

        if all_dividends:
            div_rows = []
            for div in all_dividends:
                instrument = div.get("instrument", {})
                div_rows.append({
                    "Paid On": div.get("paidOn", ""),
                    "Ticker": div.get("ticker", ""),
                    "Name": instrument.get("name", ""),
                    "Amount (£)": div.get("amount", 0),
                    "Quantity": div.get("quantity", 0),
                    "Gross/Share": div.get("grossAmountPerShare", 0),
                    "Type": div.get("type", ""),
                    "Currency": div.get("tickerCurrency", ""),
                })

            df_t212_dividends = pd.DataFrame(div_rows)
            # Use utc=True to handle mixed timezones and then strip timezone info
            df_t212_dividends["Paid On"] = pd.to_datetime(df_t212_dividends["Paid On"], utc=True, errors="coerce").dt.tz_localize(None)
            df_t212_dividends.sort_values("Paid On", ascending=False, inplace=True)
            
            # Filter out interest items to be "dividends only"
            df_t212_dividends = df_t212_dividends[~df_t212_dividends['Type'].str.contains('INTEREST', case=False, na=False)]

            total_dividends = df_t212_dividends["Amount (£)"].sum()
            st.metric("Total Dividends Received", f"£{total_dividends:,.2f}")

            st.dataframe(
                df_t212_dividends.style.format({
                    'Amount (£)': '£{:,.2f}',
                    'Quantity': '{:,.4f}',
                    'Gross/Share': '{:,.6f}',
                })
            )
        else:
            st.info("No dividends found.")

        # ============ PORTFOLIO VALUE OVER TIME ============
        st.subheader("📈 Trading 212 – Portfolio Value Over Time")

        # The logic is to fetch all historical orders, then aggregate them by fills
        order_aggregates = {}
        seen_fill_ids = set()  

        if all_orders:
            for item in all_orders:
                order = item.get("order", {})
                if order.get("status") != "FILLED":
                    continue
                order_id = order.get("id")
                fill = item.get("fill", {})

                fill_id = fill.get("id")
                if fill_id and fill_id in seen_fill_ids:
                    continue # skip duplicate fills
                if fill_id:
                    seen_fill_ids.add(fill_id)


                instrument = order.get("instrument", {})
                side = order.get("side", "")
                qty = fill.get("quantity", order.get("filledQuantity", order.get("quantity", 0)))
                
                if order_id not in order_aggregates:
                    order_aggregates[order_id] = {
                        "Date": pd.to_datetime(fill.get("filledAt", order.get("createdAt", "")), utc=True, errors="coerce"),
                        "Ticker_T212": order.get("ticker", ""),
                        "Currency": instrument.get("currency", order.get("currency", "")),
                        "Quantity": 0,
                        "Price": fill.get("price", 0),
                        "Side": side,
                    }
                order_aggregates[order_id]["Quantity"] += qty
                if fill.get("price"):
                    order_aggregates[order_id]["Price"] = fill.get("price", 0)

            trade_rows = []
            for order_id, data in order_aggregates.items():
                signed_qty = data["Quantity"] if data["Side"] == "BUY" else -data["Quantity"] # never sold, so won't know if this is correct
                trade_rows.append({
                    "Date": data["Date"],
                    "Ticker_T212": data["Ticker_T212"],
                    "Currency": data["Currency"],
                    "Signed_Qty": signed_qty,
                    "Price": data["Price"],
                    "Side": data['Side'],
                })
            df_all_trades = pd.DataFrame(trade_rows)
            df_all_trades.sort_values("Date", inplace=True)

            df_all_trades['Date'] = df_all_trades['Date'].dt.normalize() 
            df_daily_trades = df_all_trades.pivot_table(
                index='Date', 
                columns='Ticker_T212',
                values='Signed_Qty', 
                aggfunc='sum'
            ).fillna(0)

            df_fill_positions = df_daily_trades.cumsum()
            # st.table(df_fill_positions.tail(5))
            if company_name_to_ticker: # TODO: if company_name_to_ticker contains all the mapping from Ticker_T212 to Yahoo_Ticker
                df_positions_yahoo = df_fill_positions.rename(columns=company_name_to_ticker)
            else:
                print("company_name_to_ticker is empty, cannot rename columns, portfolio value over time will fail")



            # ── Yahoo finance all historical data for instruments ──
            df_all_trades['Yahoo_Ticker'] = df_all_trades['Ticker_T212'].map(company_name_to_ticker)
            
            all_prices = []

            for ticker in df_all_trades['Yahoo_Ticker'].unique():
                df1tickrt = df_all_trades[df_all_trades['Yahoo_Ticker']== ticker]
                startDate = min(df1tickrt['Date']).date()
                new_data = OHLC_YahooFinance(ticker, start_date=startDate.strftime("%Y-%m-%d")).yahooDataV8()
                new_data['ticker'] = ticker
                all_prices.append(new_data)

            price_data = pd.concat(all_prices, ignore_index=True) # Combine everything at once
            price_data = price_data[['ticker', 'Date', 'close']]
            price_data['Date'] = pd.to_datetime(price_data['Date'])
            price_data['Currency'] = price_data['ticker'].map(lambda x: df_all_trades[df_all_trades['Yahoo_Ticker'] == x]['Currency'].iloc[0])

            # get FX rate by checking if GBPUSD and GBPEUR variables already ready and waiting
            if 'GBPUSD' not in locals() or min(GBPUSD.index) <= price_data[price_data['Currency'] == 'USD']['Date'].min(): # TO_TEST, and GBPUSD only for now
                GBPUSD = get_historical_fx(price_data[price_data['Currency'] == 'USD']['Date'].min().strftime("%Y-%m-%d"))['GBPUSD=X']
            
            price_data['GBP_Close'] = price_data.apply(lambda row: row['close'] / GBPUSD.asof(row['Date']) if row['Currency'] == 'USD' else row['close']/100 if row['Currency'] == 'GBX' else row['close'], axis=1)
            
            # ====== Pivot price_data to wide format matching df_positions (Date × Yahoo_Ticker) ======
            price_wide = price_data.pivot_table(index='Date', columns='ticker', values='GBP_Close')

            # Align price_data dates to timezone-aware to match df_positions index
            price_wide.index = price_wide.index.tz_localize('UTC')

            # Reindex price_wide to match df_positions dates, forward-fill prices for weekends/holidays
            price_wide = price_wide.reindex(df_positions_yahoo.index).ffill()

            # Only use columns present in both DataFrames
            common_tickers = df_positions_yahoo.columns.intersection(price_wide.columns)
            # print(f"Common tickers: {common_tickers.tolist()}")
            # print(f"Positions-only: {df_positions_yahoo.columns.difference(price_wide.columns).tolist()}")
            # print(f"Prices-only: {price_wide.columns.difference(df_positions_yahoo.columns).tolist()}")
            # Element-wise: quantity × unit price (GBP)
            market_values = df_positions_yahoo[common_tickers] * price_wide[common_tickers]
            # Sum across instruments for total portfolio value per day
            market_values['total_value'] = market_values.sum(axis=1)
            
            # === plot the total portfolio value over time ===
            fig_t212 = ppw.t212_portfolio_value_over_time(df_all_trades, market_values)
            st.plotly_chart(fig_t212)


    except Exception as e:
        st.error(f"❌ Trading 212 API Error: {e}"); import traceback; traceback.print_exc()
        st.info("Please check your API key and secret are correct.")