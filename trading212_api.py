import requests
from typing import Dict, Any, Optional
from urllib.parse import urlencode

class Trading212API:
    """
    A Python client for the Trading 212 API.
    Provides methods for Account & Balance, Portfolio Tracking, and History & Reporting.
    """

    LIVE_URL = "https://live.trading212.com"
    DEMO_URL = "https://demo.trading212.com"

    def __init__(self, api_key: str, api_secret: Optional[str] = None, is_demo: bool = False):
        """
        Initialize the API client.
        
        :param api_key: Your Trading 212 API key.
        :param api_secret: Your Trading 212 API secret (for Basic Auth).
        :param is_demo: Set to True to use the demo environment.
        """
        import base64
        self.base_url = self.DEMO_URL if is_demo else self.LIVE_URL
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        
        if api_secret:
            # Construct Basic Auth header: base64(api_key:api_secret)
            credentials = f"{api_key}:{api_secret}"
            encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
            auth_header = f"Basic {encoded_credentials}"
        else:
            # Fallback for single token or already encoded string
            auth_header = api_key if " " in api_key else f"Basic {api_key}"

        self.session.headers.update({
            "Authorization": auth_header,
            "Content-Type": "application/json"
        })

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Helper method to make requests with retry logic for 429 errors."""
        url = f"{self.base_url}{endpoint}"
        max_retries = 3
        retry_count = 0
        
        while retry_count <= max_retries:
            response = self.session.request(method, url, **kwargs)
            
            if response.status_code == 429:
                retry_count += 1
                if retry_count > max_retries:
                    break
                
                # Check for rate limit reset time
                # x-ratelimit-reset is a Unix timestamp indicating when the limit resets
                reset_time_str = response.headers.get("x-ratelimit-reset")
                import time
                if reset_time_str:
                    try:
                        reset_time = int(reset_time_str)
                        wait_time = max(reset_time - int(time.time()) + 1, 1)
                        print(f"⚠️ Rate limited (429). Waiting {wait_time}s until reset...")
                        time.sleep(wait_time)
                        continue
                    except ValueError:
                        pass
                
                # Fallback wait if header is missing or invalid
                wait_time = 10 * retry_count
                print(f"⚠️ Rate limited (429). Waiting {wait_time}s (fallback)...")
                time.sleep(wait_time)
                continue
            
            response.raise_for_status()
            if response.text:
                return response.json()
            return {}
        
        # If we reached here, we exceeded retries
        response.raise_for_status()
        return {}

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Helper method to make GET requests."""
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Helper method to make POST requests."""
        return self._request("POST", endpoint, json=json_data)


    # ==========================================
    # 1. Account & Balance
    # ==========================================

    def get_account_summary(self) -> Dict[str, Any]:
        """
        Provides a breakdown of your account's cash and investment metrics.
        Endpoint: GET /api/v0/equity/account/summary
        Rate limit: 1 req / 5s
        """
        return self._get("/api/v0/equity/account/summary")


    # ==========================================
    # 2. Portfolio Tracking
    # ==========================================

    def get_open_positions(self, ticker: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch all open positions for your account.
        Endpoint: GET /api/v0/equity/positions
        Rate limit: 1 req / 1s
        
        :param ticker: Optional ticker to filter by (e.g., 'AAPL_US_EQ')
        """
        params = {"ticker": ticker} if ticker else None
        return self._get("/api/v0/equity/positions", params=params)


    # ==========================================
    # 3. History & Reporting
    # ==========================================

    def get_dividends(self, cursor: Optional[int] = None, ticker: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """
        Get paid out dividends.
        Endpoint: GET /api/v0/equity/history/dividends
        Rate limit: 6 req / 1m0s
        """
        params = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        if ticker:
            params["ticker"] = ticker
        return self._get("/api/v0/equity/history/dividends", params=params)

    def get_transactions(self, cursor: Optional[str] = None, time: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """
        Get transactions (superficial information about movements to and from your account).
        Endpoint: GET /api/v0/equity/history/transactions
        Rate limit: 6 req / 1m0s
        """
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if time:
            params["time"] = time
        return self._get("/api/v0/equity/history/transactions", params=params)

    def get_historical_orders(self, cursor: Optional[int] = None, ticker: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """
        Get historical orders data.
        Endpoint: GET /api/v0/equity/history/orders
        Rate limit: 6 req / 1m0s
        """
        params = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        if ticker:
            params["ticker"] = ticker
        return self._get("/api/v0/equity/history/orders", params=params)

    def get_exports(self) -> Dict[str, Any]:
        """
        List generated CSV reports.
        Endpoint: GET /api/v0/equity/history/exports
        Rate limit: 1 req / 1m0s
        """
        return self._get("/api/v0/equity/history/exports")

    def request_export_report(self, data_included: Dict[str, Any]) -> Dict[str, Any]:
        """
        Request a CSV report. 
        Note: The API spec requires a request body for this endpoint. 
        Refer to PublicReportRequest schema for payload structure.
        Endpoint: POST /api/v0/equity/history/exports
        Rate limit: 1 req / 30s
        """
        return self._post("/api/v0/equity/history/exports", json_data=data_included)

# Example Usage:
# if __name__ == '__main__':
#     import os
#     api_key = os.environ.get("TRADING212_API_KEY", "your_api_key_here")
#     client = Trading212API(api_key, is_demo=True)
#     
#     summary = client.get_account_summary()
#     print(summary)
