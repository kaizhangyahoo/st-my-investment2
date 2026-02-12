import argparse
import csv
import re
import asyncio
from datetime import datetime
from playwright.async_api import Playwright, async_playwright, expect
import logging
import os
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Limit concurrent workers
CONCURRENCY_LIMIT = 5

async def close_popups(page):
    """Attempt to close any blocking popups or promos."""
    try:
        close_selectors = [
            "button.close-icon", 
            "button[aria-label='Close']", 
            "[data-testid='close-button']",
            ".close-button",
            "button:has-text('×')"
        ]
        
        promo_text = "Never miss a market-moving event"
        promo_locator = page.locator(f"text='{promo_text}'")
        if await promo_locator.is_visible(timeout=500):
            for sel in close_selectors:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=200):
                    await btn.click()
                    return True

            try:
                buttons = await page.locator('button').all()
                for b in buttons:
                    try:
                        a = (await b.get_attribute('aria-label') or '').lower()
                        t = (await b.text_content() or '').strip().lower()
                        if 'close' in a or 'close' in t or t == '×' or 'close tour' in a or 'close tour' in t:
                            await b.click()
                            return True
                    except:
                        continue
            except:
                pass
    except:
        pass
    return False

async def extract_from_page(page_obj):
    """Robustly extract article-like text from a Playwright Page object."""
    content_selectors = ["article", ".article-body", ".news-article", ".main-content", ".content-body", ".news-detail-content"]
    try:
        await page_obj.wait_for_selector(", ".join(content_selectors), timeout=8000)
    except:
        pass

    for sel in content_selectors:
        try:
            el = page_obj.locator(sel).first
            if await el.count() > 0:
                txt = (await el.inner_text()).strip()
                if len(txt) > 100:
                    return txt
        except:
            continue

    try:
        body_text = await page_obj.evaluate("""() => {
            const body = document.body.cloneNode(true);
            ['script', 'style', 'nav', 'header', 'footer', 'promo'].forEach(tag => {
                body.querySelectorAll(tag).forEach(el => el.remove());
            });
            return body.innerText.trim();
        }""")
        return body_text
    except:
        return ""

async def extract_from_locator(locator):
    """Extract article-like text from a modal Locator."""
    content_selectors = [".news-detail-content", ".article-content", ".ig-news_detail_content", ".article-body", ".news-body", "article"]
    for sel in content_selectors:
        try:
            els = await locator.locator(sel).all()
            for el in els:
                if await el.is_visible():
                    txt = (await el.inner_text()).strip()
                    if len(txt) > 50 and "Never miss a market-moving event" not in txt[:100]:
                        return txt
        except:
            continue
    try:
        txt = (await locator.inner_text()).strip()
        promo_pattern = r"Never miss a market-moving event.*?trading experience\."
        return re.sub(promo_pattern, "", txt, flags=re.DOTALL | re.IGNORECASE).strip()
    except:
        return ""

async def scrape_news_for_instrument(page, instrument: str, max_news_items=2, existing_headlines=None) -> list[dict]:
    """Scrape news items for a specific instrument, stopping if existing headlines are found."""
    logger.info(f"Searching news for: {instrument}")
    if existing_headlines is None:
        existing_headlines = set()
    
    try:
        await page.get_by_role("listitem").filter(has_text="Search").locator("span").click()
    except:
        pass
    await page.wait_for_timeout(1000)
    
    search_box = page.get_by_role("textbox", name="Search by market name,")
    await search_box.fill("")
    await page.wait_for_timeout(300)
    await search_box.fill(instrument)
    await search_box.press("Enter")
    await page.wait_for_timeout(3000)
    
    news_items = []
    date_pattern = re.compile(r"(\d{1,2}\s*[./-]?\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*(?:[\'’]?\d{2,4})?)", re.IGNORECASE)
    date_pattern_numeric = re.compile(r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})")

    for i in range(max_news_items):
        try:
            await close_popups(page)
            headlines = await page.locator(".ig-news_headline").all()
            
            if i >= len(headlines):
                await page.evaluate("window.scrollBy(0, 500)")
                await page.wait_for_timeout(2000)
                headlines = await page.locator(".ig-news_headline").all()
                if i >= len(headlines): break
            
            headline_el = headlines[i]
            await headline_el.scroll_into_view_if_needed()
            headline = (await headline_el.get_attribute("title") or await headline_el.text_content() or "").strip()
            
            if headline in existing_headlines:
                logger.info(f"  [{instrument}] Headline '{headline[:40]}...' already exists. Stopping scrape for this instrument.")
                break

            list_date = ""
            try:
                row_text = await headline_el.evaluate("el => el.closest('.ig-news_row')?.innerText || el.parentElement.innerText")
                if row_text:
                    first_line = row_text.split('\n')[0].strip()
                    if re.match(r"^(\d{1,2}:\d{2})$", first_line):
                        list_date = datetime.now().strftime("%d %b %Y")
                    else:
                        match = date_pattern.search(row_text) or date_pattern_numeric.search(row_text)
                        if match: list_date = match.group(1).strip()
            except: pass

            row_popout_clicked = False
            try:
                row_locator = headline_el.locator("xpath=ancestor::div[contains(@class,'ig-news_row')][1]")
                if await row_locator.count() > 0:
                    popout_selectors = ["button:has-text('Open in new window')", ".ig-news-article-header_popout"]
                    for sel in popout_selectors:
                        btn = row_locator.locator(sel).first
                        if await btn.is_visible(timeout=800):
                            async with page.context.expect_page(timeout=10000) as new_page_info:
                                await btn.click()
                            new_page = await new_page_info.value
                            await new_page.wait_for_load_state('domcontentloaded')
                            link = new_page.url
                            detail_text = await extract_from_page(new_page)
                            await new_page.close()
                            row_popout_clicked = True
                            break
            except: pass

            if not row_popout_clicked:
                await headline_el.click(force=True)
            
            modal_selector = "[role='dialog'], [aria-modal='true'], .ig-news_detail, .news-detail"
            modal_found = False
            detail_text = ""
            link = ""
            detail_date = ""
            modal = None

            for _ in range(8):
                all_modals = await page.locator(modal_selector).all()
                for m in all_modals:
                    if await m.is_visible():
                        modal = m
                        modal_found = True
                        break
                if modal_found: break
                await page.wait_for_timeout(500)
            
            if modal_found:
                # Basic Modal Extraction
                detail_text = await extract_from_locator(modal)
                # Link Extraction
                for l in await modal.locator("a").all():
                    href = await l.get_attribute("href") or ""
                    if href.startswith("http") and not any(x in href.lower() for x in ["terms", "privacy"]):
                        link = href
                        break

            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
            
            final_date = detail_date if detail_date else list_date
            news_items.append({
                "date": final_date or "Date not found",
                "headline": headline,
                "link": link or "Link not found",
                "content": detail_text or "Content not found"
            })
            logger.info(f"  [{instrument}] Item {i+1}: {headline[:40]}...")
            
        except Exception as e:
            logger.error(f"  [{instrument}] Error item {i}: {e}")
            await page.keyboard.press("Escape")
            continue
    
    return news_items

def load_existing_news(filename):
    """Load headlines and data from existing CSV file."""
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            items = []
            for row in reader:
                if 'content' not in row:
                    row['content'] = "Content not found"
                items.append(row)
            return items
    except Exception as e:
        logger.error(f"Error reading existing CSV {filename}: {e}")
        return []

async def process_instrument(browser, storage_state, instrument, output_dir, max_news_items, semaphore):
    async with semaphore:
        output_csv = os.path.join(output_dir, f"ig.news.{instrument}.csv")
        existing_news = load_existing_news(output_csv)
        existing_headlines = {item['headline'] for item in existing_news}

        context = await browser.new_context(storage_state=storage_state)
        page = await context.new_page()
        try:
            await page.goto("https://www.ig.com/uk") # Base URL to ensure context loads
            # Navigate to platform - logic simplified for concurrency
            await page.goto("https://trading.ig.com/common/latest/index.html")
            await page.wait_for_timeout(10000)
            await page.get_by_title("News").click()
            await page.wait_for_timeout(2000)

            new_news_items = await scrape_news_for_instrument(page, instrument, max_news_items, existing_headlines)
            if new_news_items:
                all_news = new_news_items + existing_news
                save_to_csv(all_news, instrument, output_dir)
                save_to_markdown(all_news, instrument, output_dir)
                logger.info(f"Added {len(new_news_items)} new items for {instrument}.")
            else:
                logger.info(f"No new news items found for {instrument}.")
        except Exception as e:
            logger.error(f"Error processing {instrument}: {e}")
        finally:
            await context.close()

def save_to_csv(news_items, instrument, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"ig.news.{instrument}.csv")
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "headline", "link", "content"])
        writer.writeheader()
        writer.writerows([
            {"date": i["date"], "headline": i["headline"], "link": i["link"], "content": i.get("content", "Content not found")} 
            for i in news_items
        ])

def save_to_markdown(news_items, instrument, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"ig.news.{instrument}.md")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# News for {instrument}\n\n")
        for item in news_items:
            f.write(f"## {item['headline']}\n- **Date:** {item['date']}\n- **Link:** {item['link']}\n\n{item['content']}\n\n---\n\n")

async def run(playwright: Playwright, args, company_names):
    browser = await playwright.chromium.launch(headless=args.headless)
    
    # Login Once
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("https://www.ig.com/uk")
    await page.wait_for_timeout(2000)
    if await page.get_by_role("button", name="Accept").is_visible():
        await page.get_by_role("button", name="Accept").click()
    await page.get_by_role("link", name="Log in").click()
    await page.get_by_role("textbox", name="Email/username").fill(args.username)
    await page.get_by_role("textbox", name="Password").fill(args.password)
    await page.get_by_role("button", name="Log in").click()
    
    await expect(page.get_by_role("button", name="Open platform").first).to_be_visible(timeout=30000)
    storage_state = await context.storage_state()
    await context.close()

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    tasks = [
        process_instrument(browser, storage_state, name, args.output, args.max_news_items, semaphore)
        for name in company_names
    ]
    await asyncio.gather(*tasks)
    await browser.close()

def main():
    parser = argparse.ArgumentParser(description="Scrape IG News Concurrent")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("-u", "--username", type=str, default="shanghailondon2000")
    parser.add_argument("-p", "--password", type=str, required=True)
    parser.add_argument("--output", type=str, default=".")
    parser.add_argument("--input", type=str, required=True)
    parser.add_argument("--max-news-items", type=int, default=5)
    args = parser.parse_args()

    if args.input.endswith(".json"):
        with open(args.input, "r") as f: company_names = list(json.load(f).keys())
    else:
        with open(args.input, "r") as f: company_names = [l.strip() for l in f if l.strip()]

    async def main_async():
        async with async_playwright() as playwright:
            await run(playwright, args, company_names)

    asyncio.run(main_async())

if __name__ == "__main__":
    starttime = datetime.now()
    logger.info(f"Script started at {starttime.strftime('%Y-%m-%d %H:%M:%S')}")
    main()
    endtime = datetime.now()
    duration = endtime - starttime
    logger.info(f"Script finished at {endtime.strftime('%Y-%m-%d %H:%M:%S')}, duration: {duration}")