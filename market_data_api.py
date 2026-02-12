import pandas as pd
import miniEnc as enc
import threading
import tqdm
import requests
import json
from datetime import datetime
import io

class Finage:
    def __init__(self, api_key) -> None:     
        self.baseurl = "https://api.finage.co.uk/last/stock/changes/"
        finage = b'tbW808C4vtO8o6urmH15lnjCucbHxb6Ys2uIpcKbvsnHpbqiq5yr'
        self.finageapi = enc.decode(enc.cccccccz, finage)
        self.dl_lock = threading.Lock()
        max_concurrent_query = 8 # max concurrent query
        self.dl_semaphore = threading.Semaphore(max_concurrent_query)
        self.err_results = {}
        self.result = []
        self.api_key = api_key

    def get_finage_changes(self, symbol_list: list) -> pd.DataFrame:
        col_renames = {'lp': 'Last Price', 'cpd': 'Daily Percentage Change', 
        'cpw': 'Weekly Percentage Change', 'cpm': 'Monthly Percentage Change', 
        'cpsm': 'Six Monthly Percentage Change', 'cpy': 'Yearly Percentage Change'}
        df_changes = pd.DataFrame()
        threads = []
        for i in symbol_list:
            t = threading.Thread(target=self.query_threads, args=(i,))
            t.start()
            threads.append(t)            
        for thread in tqdm.tqdm(threads):
            thread.join()


        for i in self.result:
            df_changes = pd.concat([df_changes, i], axis=1)

        df_changes_T = df_changes.T
        df_changes_T.drop(columns=["t"], inplace=True)
        df_changes_T.rename(columns=col_renames, inplace=True)
        return df_changes_T
    
    def query_threads(self, symbol: str) -> pd.DataFrame:
        df = pd.DataFrame()
        self.dl_semaphore.acquire()
        try:
            df = pd.read_json(self.baseurl + symbol + "?apikey=" + self.api_key, typ="series")
            self.result.append(df)
        except Exception as e:
            print(e)
            self.err_results[symbol] = e
        finally:
            self.dl_semaphore.release()

class OHLC_YahooFinance:
    ''' yahoo queries copied from OHCLData class
    eg. MSCI = OHLCData("MSCI", "2022-08-08") # end date default to "today" and interval default to "1d"

    yahooV8:        MSCI = OHLCData("MSCI", "2022-08-08", "2022-08-12", "1h").yahooDataV8()
                    supported interval ["1m", "2m", "5m", "15m", "30m", "1h", "1d","5d", "1wk", "1mo"]
    yahooV7:        MSCI = OHLCData("MSCI", "2022-08-08", "2022-08-12").yahooDataV7() # interval hardcode to 1d '''
    def __init__(self, symbol, start_date, end_date = datetime.now().strftime('%Y-%m-%d'), interval = '1d'):
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.interval = str(interval)
        self.header = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_2) AppleWebKit/601.3.9 (KHTML, like Gecko) Version/9.0.2 Safari/601.3.9'}
    
    def convert_json_to_df(self, json_data):
        p = json.loads(json_data)
        ohlc_json = p['chart']['result'][0]['indicators']['quote'][0]
        dates = p['chart']['result'][0]['timestamp']
        ohlc_df = pd.DataFrame.from_dict(ohlc_json)

        if self.interval == "1d":
            ohlc_df['Date'] = [datetime.fromtimestamp(x).date() for x in dates]
        else:
            ohlc_df['Date'] = [datetime.fromtimestamp(x) for x in dates] 
        
        ohlc_df.index = ohlc_df['Date']
        return ohlc_df

    def get_epoch_time(self, date):
        return int(datetime.strptime(date, '%Y-%m-%d').timestamp())

    def yahooDataV8(self):
        if self.interval not in ["1m", "2m", "5m", "15m", "30m", "1h", "1d","5d", "1wk", "1mo"]:
            raise ValueError("Invalid Parameter for YahooV8 interval!")
        
        start_epoch = self.get_epoch_time(self.start_date)
        end_epoch = self.get_epoch_time(self.end_date)
        baseurl = "https://query1.finance.yahoo.com/v8/finance/chart/" + self.symbol
        url = f"{baseurl}?period1={start_epoch}&period2={end_epoch}&interval={self.interval}&events=history"
      
        try:
            r = requests.get(url, headers=self.header)
            r.raise_for_status()  # raises HTTPError for bad status codes
            return self.convert_json_to_df(r.text)
        except requests.RequestException as e:
            print(f"API request failed: {e}")
            raise  # re-raise so caller knows it failed

    # def yahooDataV7(self):
    #     url = "https://query1.finance.yahoo.com/v7/finance/download/" + self.symbol
    #     start_epoch = self.get_epoch_time(self.start_date)
    #     end_epoch = self.get_epoch_time(self.end_date)
    #     url += "?period1=" + str(start_epoch) + "&period2=" + str(end_epoch) + "&interval=1d&events=history&includeAdjustedClose=true"
    #     print(url)

    #     try:
    #         r = requests.get(url, headers=self.header)
    #         df = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True)
    #         return df
    #     except Exception as e:
    #         print(e)
    #         return None
    
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
        import numpy as np
        
        all_data = [
            self._fetch_ticker_data(row['Ticker'], row['FirstBuyDate'], row['LastDate'])
            for _, row in self.market_data_collections.iterrows()
        ]
        
        result = pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()
        return result.rename(columns={'ticker': 'Ticker'})
    
    def _fetch_ticker_data(self, ticker: str, start_date, end_date) -> pd.DataFrame:
        """Fetch data for a single ticker, falling back to synthetic if Yahoo fails."""
        try:
            start_str = start_date.strftime('%Y-%m-%d') if hasattr(start_date, 'strftime') else str(start_date)
            end_str = end_date.strftime('%Y-%m-%d') if end_date and hasattr(end_date, 'strftime') else None
            
            data = (OHLC_YahooFinance(ticker, start_str, end_str).yahooDataV8() 
                    if end_str else OHLC_YahooFinance(ticker, start_str).yahooDataV8())
            data['Date'] = pd.to_datetime(data['Date'])
            data['ticker'] = ticker
            return data
        except Exception as e:
            print(f"Yahoo data unavailable for {ticker}: {e}. Using synthetic data.")
            return self._generate_synthetic_data(ticker)
    
    def _generate_synthetic_data(self, ticker: str) -> pd.DataFrame:
        """Generate interpolated price data from trade history when Yahoo data is unavailable."""
        import numpy as np
        
        ticker_trades = self.trade_history[self.trade_history['Ticker'] == ticker].copy()
        ticker_trades = ticker_trades.sort_values(by='Date').reset_index(drop=True)
        
        rows = []
        for i in range(len(ticker_trades) - 1):
            start_date, end_date = ticker_trades.at[i, 'Date'], ticker_trades.at[i + 1, 'Date']
            start_price, end_price = ticker_trades.at[i, 'Price'], ticker_trades.at[i + 1, 'Price']
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


class nasdaq_data_link:
    def __init__(self) -> None:
        self.base_url = "https://data.nasdaq.com/api/v3/datasets/"
        self.ndqk = b'ud--wr-4nbzKnr-5tIzCmZjBo6o'
        self.k = enc.decode(enc.cccccccz, self.ndqk)

    def treasury_yield(self, start_date: str) -> pd.DataFrame:        
        url = self.base_url + "USTREASURY/YIELD.csv?api_key" + self.k
        try:
            df = pd.read_csv(url)
            df.index = df['Date']
        except Exception as e:
            print(e)
            df = pd.DataFrame()
        return df



if __name__ == "__main__":
    # nsdq = nasdaq_data_link()
    # print(nsdq.treasury_yield("2021-08-08"))
    # finage = Finage()
    # print(finage.sp500_change_by_sector())
    # if finage.err_results:
    #     print("Error: ", finage.err_results)
    payp = OHLC_YahooFinance("AFX.DE", "2025-12-24")
    print(payp.yahooDataV8())