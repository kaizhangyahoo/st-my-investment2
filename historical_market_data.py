import numpy as np
import pandas as pd

from getEODprice import getEODpriceFromEODHD
from market_data_api import OHLC_YahooFinance


class HistoricalMarketData:
    """Fetch historical market data from Yahoo Finance, with synthetic fallback for unavailable tickers."""

    def __init__(self, market_data_collections: pd.DataFrame, trade_history: pd.DataFrame):
        """
        Args:
            market_data_collections: DataFrame with columns ['Ticker', 'FirstBuyDate', 'LastDate']
            trade_history: DataFrame with trade history including ['Ticker', 'Date', 'Price']
        """
        self.market_data_collections = market_data_collections
        self.trade_history = trade_history

    def fetch_all(self) -> pd.DataFrame:
        """Fetch historical data for all tickers in market_data_collections.

        Returns:
            DataFrame with columns ['Date', 'Ticker', 'open', 'high', 'low', 'close', 'volume']
        """
        all_data = [
            self._fetch_ticker_data(row['Ticker'], row['FirstBuyDate'], row['LastDate'])
            for _, row in self.market_data_collections.iterrows()
        ]

        result = pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()
        return result.rename(columns={'ticker': 'Ticker'})

    def _get_eodhd_single_price(self, ticker: str):
        """Fetch latest price for a ticker from EODHD."""
        query_sym = ticker
        if '.' not in query_sym:
            query_sym = f"{query_sym}.US"
        try:
            return getEODpriceFromEODHD(query_sym)
        except Exception as e:
            print(f"Error getting EODHD price for {ticker}: {e}")
            return None

    def _fetch_eodhd_synthetic_data(self, ticker: str, start_date, end_date=None) -> pd.DataFrame:
        """Fetch latest price from EODHD and build synthetic daily OHLC rows up to end_date."""
        price = self._get_eodhd_single_price(ticker)
        if price is None:
            return pd.DataFrame()

        start_dt = pd.to_datetime(start_date)
        # iterrows() turns a None LastDate ("still held") into a truthy nan, so test for it explicitly.
        end_dt = pd.to_datetime('today') if pd.isna(end_date) else pd.to_datetime(end_date)
        business_days = pd.bdate_range(start=start_dt, end=end_dt)

        df = pd.DataFrame({
            "Date": business_days,
            "open": np.nan,
            "high": np.nan,
            "low": np.nan,
            "close": price,
            "volume": 0,
            "ticker": ticker
        })
        return df

    def _fetch_ticker_data(self, ticker: str, start_date, end_date) -> pd.DataFrame:
        """Fetch data for a single ticker, falling back to EODHD or synthetic if Yahoo fails."""
        try:
            start_str = start_date.strftime('%Y-%m-%d') if hasattr(start_date, 'strftime') else str(start_date)
            end_str = end_date.strftime('%Y-%m-%d') if end_date and hasattr(end_date, 'strftime') else None

            data = (OHLC_YahooFinance(ticker, start_str, end_str).yahooDataV8()
                    if end_str else OHLC_YahooFinance(ticker, start_str).yahooDataV8())
            data['Date'] = pd.to_datetime(data['Date'])
            data['ticker'] = ticker

            # Fix trailing/intermittent NaNs (e.g. halted/acquired stocks like SDR.L, ATKR)
            if 'close' in data.columns and data['close'].isna().any():
                data['close'] = data['close'].ffill()

                # If still NaN at start or entirely, fill with EODHD price
                if data['close'].isna().any():
                    eodhd_price = self._get_eodhd_single_price(ticker)
                    if eodhd_price is not None:
                        data['close'] = data['close'].fillna(eodhd_price)

            return data
        except Exception as e:
            print(f"Yahoo data unavailable for {ticker}: {e}. Trying EODHD synthetic fallback.")
            eodhd_df = self._fetch_eodhd_synthetic_data(ticker, start_date, end_date)
            if not eodhd_df.empty:
                return eodhd_df

            print(f"EODHD unavailable for {ticker}. Using trade history synthetic data.")
            return self._generate_synthetic_data(ticker)

    def _generate_synthetic_data(self, ticker: str) -> pd.DataFrame:
        """Generate interpolated price data from trade history when Yahoo data is unavailable."""
        ticker_trades = self.trade_history[self.trade_history['Ticker'] == ticker].copy()
        ticker_trades = ticker_trades.sort_values(by='Date').reset_index(drop=True)

        rows = []
        price_col = 'Price' if 'Price' in ticker_trades.columns else ('Price / share' if 'Price / share' in ticker_trades.columns else ('Price / Share' if 'Price / Share' in ticker_trades.columns else None))
        for i in range(len(ticker_trades) - 1):
            start_date, end_date = ticker_trades.at[i, 'Date'], ticker_trades.at[i + 1, 'Date']
            start_price = ticker_trades.at[i, price_col] if price_col else 0.0
            end_price = ticker_trades.at[i + 1, price_col] if price_col else 0.0
            business_days = pd.bdate_range(start=start_date, end=end_date)
            prices = np.linspace(start_price, end_price, num=len(business_days))

            rows.extend({
                "high": np.nan, "low": np.nan, "open": np.nan,
                "close": price / 100,  # Convert pence to pounds
                "volume": 0,
                "Date": date,
                "ticker": ticker
            } for date, price in zip(business_days, prices))

        return pd.DataFrame(rows).drop_duplicates(subset=['Date'], keep='first').reset_index(drop=True)
