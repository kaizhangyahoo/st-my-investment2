from playwright.sync_api import sync_playwright
import time

def get_finance_news(ticker, exchange):
    """
    Scrapes the latest news for a given ticker from Google Finance using Playwright.
    This bypasses the consent wall by handling the page interactions like a real browser.
    """
    url = f"https://www.google.com/finance/quote/{ticker}:{exchange}?gl=US&hl=en"
    news_items = []
    
    with sync_playwright() as p:
        # Launch browser (headless=True for invalid/server environments)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Set a real user agent
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        try:
            print(f"Navigating to {url}...")
            page.goto(url, timeout=60000)
            
            # Handle Consent Screen (if it appears)
            # Look for common consent buttons
            try:
                # Common selectors for "Accept all" or "Agree"
                consent_button = page.locator("button:has-text('Accept all')").first
                if consent_button.is_visible(timeout=3000):
                    print("Consent form detected. Clicking 'Accept all'...")
                    consent_button.click()
                    page.wait_for_load_state("networkidle")
                
                # Alternate consent button (e.g. 'I agree')
                consent_button_2 = page.locator("button:has-text('I agree')").first
                if consent_button_2.is_visible(timeout=3000):
                    print("Consent form detected. Clicking 'I agree'...")
                    consent_button_2.click()
                    page.wait_for_load_state("networkidle")

            except Exception as e:
                print(f"Consent handling skipped/failed: {e}")

            # Wait for news content
            print("Waiting for news section...")
            # We look for the "Top news" header and the list following it
            # The structure we found in inspection:
            # Container with role="list" or just looking for 'a' tags with specific classes/structure
            
            # Wait a bit for dynamic content
            page.wait_for_timeout(2000)
            
            # Extract news items
            # Using the selector strategy from inspection
            # Select all 'a' tags and filter for those that look like news cards
            
            links = page.locator("a").all()
            print(f"Found {len(links)} total links. Filtering for news...")
            
            for link in links:
                # We can replicate the heuristic: if it has 3+ div children (Source, Headline, Time)
                # But in Playwright we can check text content easily
                
                # Check for headline text div
                # A news card usually has a specific class like 'Yfwt5' which contains the headline? No classes change.
                # Let's check the text length of the children.
                
                # Improved Heuristic:
                # A news item has:
                # 1. A source (short text)
                # 2. A headline (long text)
                # 3. A time (short text, e.g. "1 hour ago")
                
                try:
                    # Get visible text of the link
                    text = link.inner_text()
                    lines = [l.strip() for l in text.split('\n') if l.strip()]
                    
                    if len(lines) >= 3:
                        # Check if it's a news item
                        # Often lines are [Source, Headline, Time, ...]
                        
                        source = lines[0]
                        headline = lines[1]
                        time_str = lines[2]
                        
                        # Verify headline is reasonable length
                        if len(headline) > 10 and len(source) < 50:
                            # Filter out false positives like "Market Summary" or similar
                            if "More news" in headline or "Quote" in headline:
                                continue
                                
                            href = link.get_attribute("href")
                            if href and (href.startswith("http") or href.startswith("./")):
                                if href.startswith("./"):
                                    href = f"https://www.google.com/finance{href[1:]}"
                                    
                                news_items.append({
                                    "headline": headline,
                                    "source": source,
                                    "time": time_str,
                                    "link": href
                                })
                except:
                    continue
            
            # Additional fallback: Check for the specific role="list" container if found
            # ...

        except Exception as e:
            print(f"Error during scraping: {e}")
        finally:
            browser.close()
            
    return news_items[:10]  # Return top 10

if __name__ == "__main__":
    ticker = "GOOGL"
    exchange = "NASDAQ"
    print(f"Scraping news for {ticker}:{exchange}...")
    news = get_finance_news(ticker, exchange)
    
    print(f"\nFound {len(news)} news items:")
    for i, item in enumerate(news, 1):
        print(f"{i}. {item['headline']}")
        print(f"   Source: {item['source']}")
        print(f"   Time: {item['time']}")
        print(f"   Link: {item['link']}\n")
