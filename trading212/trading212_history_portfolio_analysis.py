import pandas as pd
import streamlit as st
import os
import sys
import glob
from datetime import datetime, timedelta

# Add parent directory to path so we can import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from getEODprice import getEODpriceUK, getEODpriceUSA
from market_data_api import OHLC_YahooFinance, HistoricalMarketData


# ─── Ticker Mapping ───────────────────────────────────────────────────
# Trading212 tickers don't include exchange suffixes needed by Yahoo Finance.
# We infer the Yahoo ticker from the ISIN prefix and currency:
#   - ISIN starts with "US" → US stock, use ticker as-is (e.g. AMZN)
#   - ISIN starts with "CA" → Canadian stock but may trade in USD on NYSE (e.g. TRI)
#   - Currency is GBX or GBP and ISIN is GB*/IE* → LSE, append .L
#   - Currency is EUR → likely Xetra, append .DE
# This heuristic covers the majority of cases; override via TICKER_OVERRIDES.

TICKER_OVERRIDES = {
    # Add manual overrides here if needed, e.g.:
    # "CNX1": "CNX1.L",
}


def map_to_yahoo_ticker(row: pd.Series) -> str:
    """Convert a Trading212 ticker to a Yahoo Finance compatible ticker."""
    ticker = row.get("Ticker")
    if pd.isna(ticker) or ticker == "":
        return None

    # Check manual overrides first
    if ticker in TICKER_OVERRIDES:
        return TICKER_OVERRIDES[ticker]

    isin = str(row.get("ISIN", ""))
    currency = str(row.get("Currency (Price / share)", ""))

    # GBX / GBP with GB or IE ISIN → London Stock Exchange
    if currency in ("GBX", "GBP") or (isin.startswith("GB") and currency not in ("USD", "EUR")):
        return f"{ticker}.L"

    # EUR currency → Xetra
    if currency == "EUR":
        return f"{ticker}.DE"

    # US or CA ISINs traded in USD → use as-is (NYSE / NASDAQ)
    if isin.startswith("US") or isin.startswith("CA"):
        return ticker

    # IE ISINs with USD → could be LSE-listed ETF priced in USD, try .L first
    if isin.startswith("IE"):
        return f"{ticker}.L"

    # Default: use as-is
    return ticker


# ─── Data Loading ─────────────────────────────────────────────────────

@st.cache_data
def load_all_csv_files(folder: str) -> pd.DataFrame:
    """Read all from_202*.csv files, unify schemas, concatenate, and deduplicate by ID."""
    csv_files = sorted(glob.glob(os.path.join(folder, "from_202*.csv")))
    if not csv_files:
        return pd.DataFrame()

    frames = []
    for f in csv_files:
        df = pd.read_csv(f)
        # Normalise: some files have 'Currency (Result)' column, some don't
        if "Currency (Result)" in df.columns and "Currency (Total)" not in df.columns:
            df.rename(columns={"Currency (Result)": "Currency (Total)"}, inplace=True)
        frames.append(df)

    df_all = pd.concat(frames, ignore_index=True)

    # Deduplicate on `ID` column (unique transaction identifier from Trading212)
    before = len(df_all)
    df_all.drop_duplicates(subset=["ID"], keep="first", inplace=True)
    after = len(df_all)
    if before != after:
        st.info(f"ℹ️ Removed **{before - after}** duplicate rows (by ID). Kept {after} unique transactions.")

    # Parse datetime
    df_all["Time"] = pd.to_datetime(df_all["Time"], errors="coerce")
    df_all.sort_values("Time", inplace=True)
    df_all.reset_index(drop=True, inplace=True)

    return df_all


# ─── Helpers ──────────────────────────────────────────────────────────

def color_green_red(val):
    if pd.isna(val):
        return ""
    color = "green" if val > 0 else "red"
    return f"background-color: {color}"


TRADE_ACTIONS = {"Market buy", "Market sell", "Limit buy", "Limit sell", "Stop buy", "Stop sell"}


def filter_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Return only rows that are actual buy/sell trades."""
    return df[df["Action"].isin(TRADE_ACTIONS)].copy()


def calculate_direction(action: str) -> int:
    """Return +1 for buys, -1 for sells."""
    if "buy" in action.lower():
        return 1
    elif "sell" in action.lower():
        return -1
    return 0


@st.cache_data
def get_current_price(tickers: list) -> dict:
    """Fetch EOD prices using getEODprice functions."""
    uk_tickers = [t for t in tickers if t.endswith(".L") or t.endswith(".DE")]
    us_tickers = [t for t in tickers if "." not in t]
    prices = {}
    if us_tickers:
        prices.update(getEODpriceUSA(us_tickers))
    if uk_tickers:
        prices.update(getEODpriceUK(uk_tickers))
    return prices


@st.cache_data
def get_historical_fx(start_date: str) -> dict:
    """Fetch FX rates from Yahoo Finance."""
    fx_data = {}
    for pair in ["GBPUSD=X", "GBPEUR=X"]:
        try:
            data = OHLC_YahooFinance(pair, start_date).yahooDataV8()
            data.index = pd.to_datetime(data.index)
            fx_data[pair] = data["close"]
        except Exception as e:
            st.warning(f"⚠️ Could not fetch FX data for {pair}: {e}")
    return fx_data


def convert_to_gbp(row, gbpusd_rate, gbpeur_rate):
    """Convert market value to GBP based on ticker suffix."""
    ticker = row.name  # index is Yahoo ticker
    mv = row["Market Value"]
    if ticker.endswith(".L"):
        return mv  # already in GBP (or GBX → handled elsewhere)
    elif ticker.endswith(".DE"):
        return mv / gbpeur_rate
    else:
        return mv / gbpusd_rate


# ─── Market Data Accessibility Check ─────────────────────────────────

@st.cache_data
def check_ticker_accessibility(yahoo_tickers: list) -> pd.DataFrame:
    """
    For each Yahoo ticker, test:
      1. Whether OHLC_YahooFinance can fetch historical data
      2. Whether getEODprice can fetch the EOD price
    Returns a summary DataFrame.
    """
    results = []
    for ticker in yahoo_tickers:
        row = {"Yahoo Ticker": ticker}

        # Test 1: Yahoo Finance historical data (market_data_api)
        try:
            start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            data = OHLC_YahooFinance(ticker, start).yahooDataV8()
            row["Yahoo Historical"] = "✅"
            row["Last Close (Yahoo)"] = round(data["close"].iloc[-1], 4)
        except Exception as e:
            row["Yahoo Historical"] = f"❌ {e}"
            row["Last Close (Yahoo)"] = None

        # Test 2: EOD price (getEODprice)
        try:
            if ticker.endswith(".L") or ticker.endswith(".DE"):
                prices = getEODpriceUK([ticker])
            else:
                prices = getEODpriceUSA([ticker])
            eod = prices.get(ticker)
            row["EOD Price"] = "✅"
            row["EOD Value"] = eod
        except Exception as e:
            row["EOD Price"] = f"❌ {e}"
            row["EOD Value"] = None

        results.append(row)

    return pd.DataFrame(results)


# ─── Trading Summary ─────────────────────────────────────────────────

def symbol_trading_summary(df_trades: pd.DataFrame) -> pd.DataFrame:
    """Summarise first buy date, current quantity, and last date per ticker."""
    df = df_trades.copy()
    df["Signed Qty"] = df.apply(
        lambda r: r["No. of shares"] * calculate_direction(r["Action"]), axis=1
    )
    g = df.groupby("Yahoo Ticker")

    out = pd.DataFrame({
        "Ticker": g["Yahoo Ticker"].first(),
        "FirstBuyDate": g["Time"].min().dt.date,
        "CurrentQuantity": g["Signed Qty"].sum(),
        "LastDate": g["Time"].max().dt.date,
    }).reset_index(drop=True)

    # If still held → set LastDate to None (for HistoricalMarketData)
    out.loc[out["CurrentQuantity"] != 0, "LastDate"] = None
    return out


# ═══════════════════════════════════════════════════════════════════════
# STREAMLIT APP
# ═══════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Trading212 Portfolio Analysis", layout="wide")
st.title("📊 Trading212 Portfolio Analysis")

# Determine CSV folder (same folder as this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

df_all = load_all_csv_files(SCRIPT_DIR)

if df_all.empty:
    st.error("No `from_202*.csv` files found in the trading212 folder.")
    st.stop()

st.success(f"✅ Loaded **{len(df_all)}** unique transactions from **{len(glob.glob(os.path.join(SCRIPT_DIR, 'from_202*.csv')))}** CSV files.")

# ─── Raw Data Preview ─────────────────────────────────────────────────
with st.expander("📋 Raw Transaction Data", expanded=False):
    st.dataframe(df_all, width="stretch", height=400)

# ─── Filter Trades Only ──────────────────────────────────────────────
df_trades = filter_trades(df_all)
df_trades["Direction"] = df_trades["Action"].apply(calculate_direction)
df_trades["Signed Qty"] = df_trades["No. of shares"] * df_trades["Direction"]

# Map to Yahoo tickers
df_trades["Yahoo Ticker"] = df_trades.apply(map_to_yahoo_ticker, axis=1)

st.header("🔄 Trades Overview")
st.write(f"Found **{len(df_trades)}** trade transactions across **{df_trades['Ticker'].nunique()}** instruments.")

# Show ticker mapping
with st.expander("🗺️ Ticker Mapping (Trading212 → Yahoo Finance)", expanded=True):
    ticker_map = (
        df_trades[["Ticker", "ISIN", "Name", "Currency (Price / share)", "Yahoo Ticker"]]
        .drop_duplicates(subset=["Ticker"])
        .sort_values("Ticker")
        .reset_index(drop=True)
    )
    st.dataframe(ticker_map, width="stretch")

# ─── Market Data Accessibility Check ─────────────────────────────────
st.header("🔍 Market Data Accessibility Check")
st.write("Testing whether each ticker's EOD price and historical data can be accessed via `market_data_api` and `getEODprice`...")

unique_yahoo_tickers = df_trades["Yahoo Ticker"].dropna().unique().tolist()

if st.button("🧪 Run Accessibility Check", type="primary"):
    with st.spinner("Checking tickers... this may take a moment."):
        df_check = check_ticker_accessibility(unique_yahoo_tickers)
    st.dataframe(
        df_check.style.map(
            lambda v: "background-color: #d4edda" if v == "✅" else ("background-color: #f8d7da" if isinstance(v, str) and v.startswith("❌") else ""),
            subset=["Yahoo Historical", "EOD Price"]
        ),
        width="stretch",
    )

    # Summary
    yahoo_ok = (df_check["Yahoo Historical"] == "✅").sum()
    eod_ok = (df_check["EOD Price"] == "✅").sum()
    total = len(df_check)
    st.markdown(f"""
    **Results Summary:**
    - Yahoo Finance Historical: **{yahoo_ok}/{total}** tickers accessible
    - EOD Price API: **{eod_ok}/{total}** tickers accessible
    """)

# ─── Trade History This Quarter ───────────────────────────────────────
st.header("📅 Trade History This Quarter")
today = datetime.now()
current_quarter = pd.Period(today, freq="Q")
df_quarter = df_trades[df_trades["Time"].dt.to_period("Q") == current_quarter]
if df_quarter.empty:
    st.info("No trades this quarter.")
else:
    st.dataframe(
        df_quarter[["Time", "Action", "Ticker", "Name", "No. of shares", "Price / share", "Currency (Price / share)", "Total", "Currency (Total)"]],
        width="stretch",
    )

# ─── Current Positions ───────────────────────────────────────────────
st.header("💼 Current Positions")

df_positions = df_trades.groupby("Yahoo Ticker").agg({
    "Signed Qty": "sum",
    "Name": "last",
    "Ticker": "last",
    "Currency (Price / share)": "last",
    "Total": "sum",
}).rename(columns={
    "Signed Qty": "Quantity",
    "Currency (Price / share)": "Currency",
    "Total": "Total Cost",
})

# Keep only open positions (non-zero quantity)
df_positions = df_positions[df_positions["Quantity"].abs() > 1e-8]

if df_positions.empty:
    st.info("No open positions.")
else:
    st.write(f"You currently hold **{len(df_positions)}** instruments.")

    # Attempt to fetch current prices
    try:
        current_prices = get_current_price(df_positions.index.tolist())
        df_positions["Current Price"] = df_positions.index.map(current_prices)
        df_positions["Current Price"] = pd.to_numeric(df_positions["Current Price"], errors="coerce")
        df_positions["Market Value"] = df_positions["Quantity"] * df_positions["Current Price"]
    except Exception as e:
        st.warning(f"⚠️ Could not fetch current prices: {e}")
        df_positions["Current Price"] = None
        df_positions["Market Value"] = None

    # FX conversion to GBP
    try:
        earliest_date = df_trades["Time"].min().strftime("%Y-%m-%d")
        fx_data = get_historical_fx(earliest_date)
        GBPUSD = fx_data.get("GBPUSD=X")
        GBPEUR = fx_data.get("GBPEUR=X")

        if GBPUSD is not None and GBPEUR is not None:
            gbpusd_rate = GBPUSD.iloc[-1]
            gbpeur_rate = GBPEUR.iloc[-1]
            df_positions["Market Value GBP"] = df_positions.apply(
                lambda r: convert_to_gbp(r, gbpusd_rate, gbpeur_rate), axis=1
            )

            # For GBX-priced instruments, values are in pence → divide by 100
            for idx in df_positions.index:
                orig_currency = df_trades[df_trades["Yahoo Ticker"] == idx]["Currency (Price / share)"].iloc[0] if len(df_trades[df_trades["Yahoo Ticker"] == idx]) > 0 else ""
                if orig_currency == "GBX":
                    df_positions.loc[idx, "Market Value GBP"] = df_positions.loc[idx, "Market Value GBP"] / 100

            total_gbp = df_positions["Market Value GBP"].sum()
            st.metric("Total Portfolio Value (GBP)", f"£{total_gbp:,.2f}")
        else:
            st.warning("⚠️ FX data unavailable, cannot convert to GBP.")
    except Exception as e:
        st.warning(f"⚠️ FX conversion failed: {e}")

    # Display positions table
    display_cols = ["Name", "Ticker", "Quantity", "Currency", "Current Price", "Market Value"]
    if "Market Value GBP" in df_positions.columns:
        display_cols.append("Market Value GBP")

    st.dataframe(
        df_positions[display_cols].style.format({
            "Quantity": "{:,.4f}",
            "Current Price": "{:,.4f}",
            "Market Value": "{:,.2f}",
            **({} if "Market Value GBP" not in df_positions.columns else {"Market Value GBP": "£{:,.2f}"}),
        }),
        width="stretch",
        height=600,
    )

# ─── Single Ticker History ───────────────────────────────────────────
st.header("🔎 Single Instrument Trade History")

ticker_options = sorted(df_trades["Name"].dropna().unique().tolist())
selected_instrument = st.selectbox("Select an instrument", options=ticker_options, key="t212_instrument")

if selected_instrument:
    df_instrument = df_trades[df_trades["Name"] == selected_instrument].sort_values("Time", ascending=False)
    st.subheader(f"Trade History for {selected_instrument}")
    st.dataframe(
        df_instrument[["Time", "Action", "Ticker", "Yahoo Ticker", "No. of shares", "Price / share", "Currency (Price / share)", "Total"]],
        width="stretch",
    )

# ─── Non-Trade Transactions Summary ──────────────────────────────────
st.header("💰 Non-Trade Transactions Summary")

NON_TRADE_ACTIONS = {"Deposit", "Withdrawal", "Dividend (Dividend)", "Interest on cash",
                     "Spending cashback", "Currency conversion"}

df_non_trades = df_all[~df_all["Action"].isin(TRADE_ACTIONS)].copy()

if not df_non_trades.empty:
    cashflow_summary = df_non_trades.groupby("Action").agg(
        Count=("Total", "size"),
        Total_Amount=("Total", "sum"),
    ).sort_values("Total_Amount", ascending=False)

    col1, col2 = st.columns(2)

    with col1:
        deposits = df_non_trades[df_non_trades["Action"] == "Deposit"]["Total"].sum()
        st.metric("Total Deposits", f"£{deposits:,.2f}")

    with col2:
        dividends_mask = df_non_trades["Action"].str.contains("Dividend", case=False, na=False)
        dividends = df_non_trades[dividends_mask]["Total"].sum()
        st.metric("Total Dividends Received", f"£{dividends:,.2f}")

    st.dataframe(cashflow_summary.style.format({"Total_Amount": "£{:,.2f}"}), width="stretch")
else:
    st.info("No non-trade transactions found.")
