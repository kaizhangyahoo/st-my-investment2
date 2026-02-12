import requests
from typing import Optional, List, Dict, Any, Union

class NewsAPIClient:
    """
    Client for News API (newsapi.org).
    Follows structure similar to AlpacaMarketDataClient.
    """
    
    def __init__(self, api_key: str, base_url: str = "https://newsapi.org"):
        self.base_url = base_url.rstrip('/')
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Helper method to make GET requests."""
        url = f"{self.base_url}{endpoint}"
        # Filter out None values from params
        if params:
            params = {k: v for k, v in params.items() if v is not None}
            
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    # ==========================================
    # Main Endpoints
    # ==========================================

    def get_everything(self, q: Optional[str] = None, q_in_title: Optional[str] = None,
                       sources: Optional[Union[str, List[str]]] = None, 
                       domains: Optional[Union[str, List[str]]] = None,
                       exclude_domains: Optional[Union[str, List[str]]] = None,
                       from_param: Optional[str] = None, to: Optional[str] = None,
                       language: Optional[str] = None, sort_by: Optional[str] = None,
                       page_size: int = 100, page: int = 1) -> Dict[str, Any]:
        """
        Search through millions of articles from over 80,000 large and small news sources and blogs.
        /v2/everything
        example params: q="aapl", sources="financial-times", from_param="2025-12-15", to="2025-12-17", language="en", sort_by="publishedAt", page_size=120, page=1
        """
        endpoint = "/v2/everything"
        
        # Helper to join lists if provided
        def _join_if_list(val):
            if isinstance(val, list):
                return ",".join(val)
            return val

        params = {
            "q": q,
            "qInTitle": q_in_title,
            "sources": _join_if_list(sources),
            "domains": _join_if_list(domains),
            "excludeDomains": _join_if_list(exclude_domains),
            "from": from_param,
            "to": to,
            "language": language,
            "sortBy": sort_by,
            "pageSize": page_size,
            "page": page
        }
        return self._get(endpoint, params)

    def get_top_headlines(self, country: Optional[str] = None, category: Optional[str] = None,
                          sources: Optional[Union[str, List[str]]] = None, q: Optional[str] = None,
                          page_size: int = 20, page: int = 1) -> Dict[str, Any]:
        """
        Returns live top and breaking headlines for a country, specific category in a country, 
        or for a single source.
        /v2/top-headlines
        """
        endpoint = "/v2/top-headlines"
        
        # Helper to join lists if provided
        def _join_if_list(val):
            if isinstance(val, list):
                return ",".join(val)
            return val

        params = {
            "country": country,
            "category": category,
            "sources": _join_if_list(sources),
            "q": q,
            "pageSize": page_size,
            "page": page
        }
        return self._get(endpoint, params)

    def get_sources(self, category: Optional[str] = None, language: Optional[str] = None,
                    country: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns the subset of news publishers that top headlines are available from.
        /v2/top-headlines/sources
        """
        endpoint = "/v2/top-headlines/sources"
        params = {
            "category": category,
            "language": language,
            "country": country
        }
        return self._get(endpoint, params)


if __name__ == "__main__":
    newsapi = NewsAPIClient(api_key="my_api_key")
    print(newsapi.get_everything(q="gold price", sources=["bloomberg","business-insider"], from_param="2025-12-15", to="2025-12-17", language="en", sort_by="publishedAt", page_size=100, page=1))
    # print(newsapi.get_sources(category="business", language="en", country="us"))