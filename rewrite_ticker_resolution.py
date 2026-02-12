import requests

def use_sec_site(missing_symobols: list[str]) -> dict:
    url = "https://www.sec.gov/files/company_tickers.json"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "MyApp/1.0 (contact: you@example.com) Mozilla/5.0 (Macintosh)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.sec.gov/",
        "Accept-Language": "en-US,en;q=0.9",
    })

    # retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429,500,502,503,504])
    # session.mount("https://", HTTPAdapter(max_retries=retries))

    resp = session.get(url, timeout=10, allow_redirects=True)
    print(resp.status_code)
    resp.raise_for_status()
    sec_raw_dict = resp.json()
    # sec_raw_dict looks like this:
    #     {'0': {'cik_str': 1045810, 'ticker': 'NVDA', 'title': 'NVIDIA CORP'},
    #   '1': {'cik_str': 320193, 'ticker': 'AAPL', 'title': 'Apple Inc.'},
    #   '2': {'cik_str': 1652044, 'ticker': 'GOOGL', 'title': 'Alphabet Inc.'},
    sec_symbols = {item['ticker']: item['title'] for item in sec_raw_dict.values()}

    potential_match = {}
    for i in missing_symobols:
        first_word_from_missing_symbol = i.split(" ")[0]
        # search all sec_symbols values that contain i
        matches = {k: v for k, v in sec_symbols.items() if first_word_from_missing_symbol.lower() in v.lower()}
        potential_match[i] = next(iter(matches), None) # first (key, value) pair
    return potential_match

if __name__ == "__main__":
    missing_symbols = ["Apple Incorporated", "Alphabet Company", "Microsoft Corp", "Tesla Motors", "RTX Corporation (All Sessions)", "Barrick Gold Corp - US (All Sessions)" ]
    result = use_sec_site(missing_symbols)
    print(result)