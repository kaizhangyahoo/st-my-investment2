import requests
from bs4 import BeautifulSoup

def get_finance_news(ticker, exchange):
    """
    ATTEMPT to scrape news using requests.
    NOTE: Google Finance often blocks requests or redirects to a consent page (EU/UK).
    This script requires valid cookies (SID, SIDCC, etc.) to bypass the consent wall.
    Use 'scrape_news_playwright.py' for a robust, automated solution.
    """
    url = f"https://www.google.com/finance/quote/{ticker}:{exchange}?gl=US&hl=en"
    
    # 2. Set headers to mimic a real browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 3. Add cookies to bypass consent wall if available
    # You must extract these from a real browser session (Developer Tools > Application > Cookies)
    cookies = {
        # "SID": "PASTE_YOUR_SID_HERE",
        # "SIDCC": "PASTE_YOUR_SIDCC_HERE",
        # ...
    }
    
    try:
        response = requests.get(url, headers=headers, cookies=cookies)
        response.raise_for_status()
        
        # Check if we were redirected to consent page
        if "consent.google.com" in response.url:
            print("Blocked by consent wall. Please use the Playwright script or provide valid cookies.")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        
        news_items = []
        links = soup.find_all("a")
        for link in links:
            divs = link.find_all("div", recursive=False)
            if len(divs) >= 3:
                # Heuristic for news card based on observed structure
                # This might change as Google updates classes/structure
                if len(divs) > 2:
                    headline = divs[2].text.strip()
                    source = divs[1].text.strip()
                    if headline and len(headline) > 10:
                        href = link.get("href")
                        if href and href.startswith("./"):
                            href = f"https://www.google.com/finance{href[1:]}"
                        
                        # filter noise
                        if "More news" not in headline:
                            news_items.append({"headline": headline, "source": source, "link": href})
                     
        return news_items[:10]

    except Exception as e:
        print(f"An error occurred: {e}")
        return []

if __name__ == "__main__":
    news = get_finance_news("GOOGL", "NASDAQ")
    print(f"Found {len(news)} items.")
    for n in news:
        print(n)

