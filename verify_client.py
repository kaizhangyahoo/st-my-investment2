import unittest
from unittest.mock import MagicMock, patch
from alpaca_client import AlpacaMarketDataClient

class TestAlpacaMarketDataClient(unittest.TestCase):
    def setUp(self):
        self.client = AlpacaMarketDataClient("test_key", "test_secret")

    @patch('requests.get')
    def test_get_stock_bars(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"bars": []}
        mock_get.return_value = mock_response

        self.client.get_stock_bars("AAPL", "1Min", "2023-01-01")

        mock_get.assert_called_with(
            "https://data.alpaca.markets/v2/stocks/AAPL/bars",
            headers={
                "Apca-Api-Key-Id": "test_key",
                "Apca-Api-Secret-Key": "test_secret",
                "Content-Type": "application/json"
            },
            params={
                "start": "2023-01-01",
                "timeframe": "1Min",
                "limit": 1000,
                "feed": "sip",
                "adjustment": "raw"
            }
        )

    @patch('requests.get')
    def test_get_crypto_trades(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"trades": []}
        mock_get.return_value = mock_response

        self.client.get_crypto_trades(["BTC/USD", "ETH/USD"], "2023-01-01")

        mock_get.assert_called_with(
            "https://data.alpaca.markets/v1beta2/crypto/trades",
            headers={
                "Apca-Api-Key-Id": "test_key",
                "Apca-Api-Secret-Key": "test_secret",
                "Content-Type": "application/json"
            },
            params={
                "symbols": "BTC/USD,ETH/USD",
                "start": "2023-01-01",
                "limit": 1000
            }
        )

    @patch('requests.get')
    def test_get_news(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"news": []}
        mock_get.return_value = mock_response

        self.client.get_news(symbols=["AAPL"], limit=10)

        mock_get.assert_called_with(
            "https://data.alpaca.markets/v1beta1/news",
            headers={
                "Apca-Api-Key-Id": "test_key",
                "Apca-Api-Secret-Key": "test_secret",
                "Content-Type": "application/json"
            },
            params={
                "symbols": "AAPL",
                "limit": 10,
                "sort": "ASC",
                "include_content": "true",
                "exclude_contentless": "true"
            }
        )

if __name__ == '__main__':
    unittest.main()
