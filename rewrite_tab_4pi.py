import pandas as pd
import streamlit as st
import numpy as np
import json
import os
from datetime import datetime, timedelta
from rewrite_ticker_resolution import use_sec_site
from getEODprice import getEODpriceUK, getEODpriceUSA
import rewrite_plot_portfolio_weights as ppw # TODO: rename to make it more intuitive
from market_data_api import OHLC_YahooFinance, HistoricalMarketData
import glob, socket, platform


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


st.title("Portfolio Management Dashboard and Analytics")

st.header("Upload Trade/Transaction History")
uploaded_file = st.file_uploader('''\
Upload your trade/transaction history in CSV format. Filename must be in the format of: \n
1. trade file must have filename start with Trade*.csv \n
2. transaction file must have filename start with Transaction*.csv''', type=["csv"], accept_multiple_files=True)

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
    # extend with file paths (strings)
    files_to_process.extend(trade_files + trans_files)

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



            # plot portfolio weights TODO: buggy, eg use any symbol highlight won't work
            standout = [0.0] * len(df_current_positions)  # selected instrument highlight
            instruments_list = df_current_positions['Market'].tolist()
            if selected_company in instruments_list:
                idx = instruments_list.index(selected_company)
                standout[idx] = 0.5
            current_GBP_rate = {'GBPUSD=X': GBPUSD.iloc[-1], 'GBPEUR=X': GBPEUR.iloc[-1]}
            fig = ppw.plot_portfolio_weights(df_current_positions, standout, current_GBP_rate)
            st.plotly_chart(fig, use_container_width=True)


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
            

            fig_portfolio = ppw.portfolio_value_over_time(df_portfolio_history, account_id)
            st.plotly_chart(fig_portfolio, use_container_width=True)

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
            if left1.button("1y", use_container_width=True):
                selected_date = calculate_past_date("1y")
            if left2.button("6m", use_container_width=True):
                selected_date = calculate_past_date("6m")
            if middle1.button("3m", use_container_width=True):
                selected_date = calculate_past_date("3m")
            if middle2.button("1m", use_container_width=True):
                selected_date = calculate_past_date("1m")
            if right1.button("1w", use_container_width=True):
                selected_date = calculate_past_date("1w")
            if right2.button("1d", use_container_width=True):
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
            st.plotly_chart(fig, use_container_width=True)