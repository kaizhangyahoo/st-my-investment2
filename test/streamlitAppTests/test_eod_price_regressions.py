"""Regression tests for KAN-21, KAN-22 and KAN-23.

Each test reproduces the exact failure described in the ticket, so a revert of the
fix in commit 5d659aa turns the test red. Every market-data provider is stubbed:
no test here is allowed to reach Yahoo, EODHD or TwelveData.
"""
import unittest
from datetime import date
from unittest import mock

import pandas as pd
import requests

import getEODprice
import historical_market_data
from historical_market_data import HistoricalMarketData


def _ohlc(close: float) -> pd.DataFrame:
    """Minimal frame shaped like OHLC_YahooFinance.yahooDataV8() output."""
    return pd.DataFrame({'close': [close], 'Date': [date(2026, 11, 16)]})


def _yahoo_stub(behaviour: dict):
    """Build a fake OHLC_YahooFinance whose behaviour is keyed by symbol.

    A dict value is returned as a frame; an exception instance is raised.
    """
    calls = []

    class Stub:
        def __init__(self, symbol, start_date, end_date=None, interval='1d'):
            self.symbol = symbol
            calls.append((symbol, str(start_date)))

        def yahooDataV8(self):
            outcome = behaviour[self.symbol]
            if isinstance(outcome, list):          # one outcome per attempt
                outcome = outcome[min(len(outcome) - 1,
                                      sum(1 for c in calls if c[0] == self.symbol) - 1)]
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    return Stub, calls


class TestKan22YahooLastCloses(unittest.TestCase):
    """KAN-22: getEODpriceUK raised NameError and masked the real Yahoo failure."""

    def test_request_exception_does_not_raise_nameerror(self):
        stub, _ = _yahoo_stub({'SDR.L': requests.RequestException('503 boom')})
        with mock.patch.object(getEODprice, 'OHLC_YahooFinance', stub):
            result = getEODprice.getEODpriceUK(['SDR.L'])
        # Pre-fix this line never ran: `close_price` was unbound -> NameError.
        self.assertEqual(result, {}, "failed symbol must be omitted, not priced")

    def test_failing_symbol_does_not_inherit_previous_price(self):
        """The dangerous half of KAN-22: a stale DataFrame carried across iterations."""
        stub, _ = _yahoo_stub({
            'OK.L': _ohlc(1000.0),
            'BAD.L': requests.RequestException('503 boom'),
        })
        with mock.patch.object(getEODprice, 'OHLC_YahooFinance', stub):
            result = getEODprice.getEODpriceUK(['OK.L', 'BAD.L'])

        self.assertEqual(list(result), ['OK.L'])
        self.assertAlmostEqual(result['OK.L'], 10.0)        # 1000p -> £10
        self.assertNotIn('BAD.L', result,
                         "BAD.L must not silently take OK.L's price")

    def test_keyerror_without_timestamp_is_skipped(self):
        stub, _ = _yahoo_stub({'BAD.L': KeyError('chart')})
        with mock.patch.object(getEODprice, 'OHLC_YahooFinance', stub):
            result = getEODprice.getEODpriceUK(['BAD.L'])
        self.assertEqual(result, {})

    def test_keyerror_on_later_symbol_does_not_silently_reuse_earlier_price(self):
        """The silent variant: pre-fix BAD.L was priced at OK.L's close, with no error."""
        stub, _ = _yahoo_stub({
            'OK.L': _ohlc(1000.0),
            'BAD.L': KeyError('chart'),   # not a 'timestamp' KeyError -> falls through
        })
        with mock.patch.object(getEODprice, 'OHLC_YahooFinance', stub):
            result = getEODprice.getEODpriceUK(['OK.L', 'BAD.L'])

        self.assertEqual(result.get('BAD.L'), None,
                         "pre-fix BAD.L was reported as 10.0, OK.L's price")
        self.assertAlmostEqual(result['OK.L'], 10.0)

    def test_keyerror_with_timestamp_retries_earlier_business_day(self):
        stub, calls = _yahoo_stub({'SDR.L': [KeyError('timestamp'), _ohlc(500.0)]})
        with mock.patch.object(getEODprice, 'OHLC_YahooFinance', stub):
            result = getEODprice.getEODpriceUK(['SDR.L'])

        self.assertAlmostEqual(result['SDR.L'], 5.0)
        self.assertEqual(len(calls), 2, "should retry exactly once")
        self.assertLess(calls[1][1], calls[0][1], "retry must step back a day")

    def test_failed_retry_is_skipped_not_raised(self):
        stub, _ = _yahoo_stub({'SDR.L': [KeyError('timestamp'),
                                         requests.RequestException('503 boom')]})
        with mock.patch.object(getEODprice, 'OHLC_YahooFinance', stub):
            result = getEODprice.getEODpriceUK(['SDR.L'])
        self.assertEqual(result, {})


class TestKan21Eodhd402Fallback(unittest.TestCase):
    """KAN-21: the 402 branch returned a dict, and at the wrong unit."""

    @staticmethod
    def _resp_402():
        r = mock.Mock(spec=requests.Response)
        r.status_code = 402
        r.text = 'Daily request limit reached'
        return r

    def test_lse_402_returns_float_in_pounds(self):
        stub, _ = _yahoo_stub({'SDR.L': _ohlc(1234.0)})
        with mock.patch.object(getEODprice.requests, 'get', return_value=self._resp_402()), \
             mock.patch.object(getEODprice, 'OHLC_YahooFinance', stub):
            price = getEODprice.getEODpriceFromEODHD('SDR.L', api_token='test-token')

        self.assertNotIsInstance(price, dict, "pre-fix this was {'SDR.L': 12.34}")
        self.assertIsInstance(price, float)
        self.assertAlmostEqual(price, 12.34)   # 1234p -> £12.34

    def test_xetra_402_returns_euros_unscaled(self):
        """The unit half of KAN-21: .DE is already in euros, so no /100."""
        stub, _ = _yahoo_stub({'AFX.DE': _ohlc(46.8)})
        with mock.patch.object(getEODprice.requests, 'get', return_value=self._resp_402()), \
             mock.patch.object(getEODprice, 'OHLC_YahooFinance', stub):
            price = getEODprice.getEODpriceFromEODHD('AFX.DE', api_token='test-token')

        self.assertIsInstance(price, float)
        self.assertAlmostEqual(price, 46.8,
                               msg="pre-fix this returned 0.468 (wrongly /100)")

    def test_us_402_does_not_return_a_pence_scaled_price(self):
        with mock.patch.object(getEODprice.requests, 'get', return_value=self._resp_402()):
            price = getEODprice.getEODpriceFromEODHD('AAPL.US', api_token='test-token')
        self.assertIsNone(price, "a US symbol must never take the /100 LSE path")

    def test_list_input_maps_symbols_to_floats(self):
        stub, _ = _yahoo_stub({'SDR.L': _ohlc(1234.0), 'AFX.DE': _ohlc(46.8)})
        with mock.patch.object(getEODprice.requests, 'get', return_value=self._resp_402()), \
             mock.patch.object(getEODprice, 'OHLC_YahooFinance', stub):
            prices = getEODprice.getEODpriceFromEODHD(['SDR.L', 'AFX.DE'],
                                                      api_token='test-token')

        self.assertAlmostEqual(prices['SDR.L'], 12.34)
        self.assertAlmostEqual(prices['AFX.DE'], 46.8)
        for value in prices.values():
            self.assertNotIsInstance(value, dict)


class TestEodhd200LseConversion(unittest.TestCase):
    """LSE quotes in pence (close, previousClose, or EOD fallback) must convert to GBP on 200."""

    @staticmethod
    def _resp_200(data):
        r = mock.Mock(spec=requests.Response)
        r.status_code = 200
        r.json.return_value = data
        return r

    def test_lse_200_close_returns_pounds(self):
        resp = self._resp_200({"code": "SDR.LSE", "close": 1234.0})
        with mock.patch.object(getEODprice.requests, 'get', return_value=resp):
            price = getEODprice.getEODpriceFromEODHD('SDR.L', api_token='test-token')
        self.assertAlmostEqual(price, 12.34)

    def test_lse_200_previous_close_returns_pounds(self):
        resp = self._resp_200({"code": "SDR.LSE", "previousClose": 1234.0})
        with mock.patch.object(getEODprice.requests, 'get', return_value=resp):
            price = getEODprice.getEODpriceFromEODHD('SDR.L', api_token='test-token')
        self.assertAlmostEqual(price, 12.34)

    def test_xetra_200_returns_euros_unscaled(self):
        resp = self._resp_200({"code": "AFX.XETRA", "close": 46.8})
        with mock.patch.object(getEODprice.requests, 'get', return_value=resp):
            price = getEODprice.getEODpriceFromEODHD('AFX.DE', api_token='test-token')
        self.assertAlmostEqual(price, 46.8)

    def test_lse_200_eod_historical_fallback_returns_pounds(self):
        rt_fail = mock.Mock(spec=requests.Response, status_code=500)
        eod_ok = self._resp_200([{"code": "SDR.LSE", "close": 1234.0}])
        with mock.patch.object(getEODprice.requests, 'get', side_effect=[rt_fail, eod_ok]):
            price = getEODprice.getEODpriceFromEODHD('SDR.L', api_token='test-token')
        self.assertAlmostEqual(price, 12.34)


class TestKan23SyntheticEndDate(unittest.TestCase):
    """KAN-23: a missing LastDate produced NaT and crashed bdate_range.

    `if end_date` only screened out None; nan and NaT are truthy and reached
    pd.to_datetime, which turned them into NaT. The fix tests pd.isna() instead.
    """

    def setUp(self):
        self.trade_history = pd.DataFrame({
            'Ticker': ['SDR.L'],
            'Date': [pd.Timestamp('2026-01-05')],
            'Price': [500.0],
        })

    def _engine(self, collections):
        return HistoricalMarketData(collections, self.trade_history)

    def test_nan_end_date_runs_to_today(self):
        engine = self._engine(pd.DataFrame())
        with mock.patch.object(engine, '_get_eodhd_single_price', return_value=12.34):
            df = engine._fetch_eodhd_synthetic_data(
                'SDR.L', date(2026, 1, 5), float('nan'))   # truthy, so pre-fix -> NaT

        self.assertFalse(df.empty)
        self.assertGreaterEqual(df['Date'].max(),
                                pd.Timestamp('today').normalize() - pd.Timedelta(days=4))

    def test_none_end_date_runs_to_today(self):
        engine = self._engine(pd.DataFrame())
        with mock.patch.object(engine, '_get_eodhd_single_price', return_value=12.34):
            df = engine._fetch_eodhd_synthetic_data('SDR.L', date(2026, 1, 5), None)
        self.assertFalse(df.empty)

    def test_explicit_end_date_still_honoured(self):
        engine = self._engine(pd.DataFrame())
        with mock.patch.object(engine, '_get_eodhd_single_price', return_value=12.34):
            df = engine._fetch_eodhd_synthetic_data(
                'SDR.L', date(2026, 1, 5), date(2026, 1, 9))

        self.assertEqual(df['Date'].min(), pd.Timestamp('2026-01-05'))
        self.assertEqual(df['Date'].max(), pd.Timestamp('2026-01-09'))

    def _fetch_all_with_last_date(self, last_date):
        """Run the real fetch_all() for one held ticker that Yahoo cannot price."""
        collections = pd.DataFrame({
            'Ticker': ['SDR.L'],
            'FirstBuyDate': [date(2026, 1, 5)],
            'LastDate': [last_date],
        })
        stub, _ = _yahoo_stub({'SDR.L': requests.RequestException('503 boom')})
        engine = self._engine(collections)

        with mock.patch.object(historical_market_data, 'OHLC_YahooFinance', stub), \
             mock.patch.object(historical_market_data, 'getEODpriceFromEODHD',
                               return_value=12.34):
            return engine.fetch_all()

    def test_fetch_all_survives_nat_last_date(self):
        """End-to-end repro. Pre-fix: ValueError: Neither `start` nor `end` can be NaT.

        Both NaT and nan are truthy, so the pre-fix `if end_date` test waved them
        through to bdate_range. Only `None` was falsy enough to be caught, which is
        why symbol_trading_summary's own still-held rows never tripped it.
        """
        df = self._fetch_all_with_last_date(pd.NaT)

        self.assertFalse(df.empty)
        self.assertEqual(set(df['Ticker']), {'SDR.L'})
        self.assertTrue((df['close'] == 12.34).all())

    def test_fetch_all_with_none_last_date(self):
        """Guard, not a regression: `None` is falsy, so this already worked pre-fix."""
        df = self._fetch_all_with_last_date(None)
        self.assertFalse(df.empty)
        self.assertTrue((df['close'] == 12.34).all())


if __name__ == '__main__':
    unittest.main(verbosity=2)
