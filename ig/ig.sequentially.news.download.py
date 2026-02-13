import argparse
import sys
import csv
import re
from datetime import datetime, timedelta
from playwright.sync_api import Playwright, sync_playwright, expect
import logging
import os
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# TODO: logging file handler, location, rotating logs, etc. for better debugging and record-keeping


def close_popups(page):
    """Attempt to close any blocking popups or promos."""
    try:
        # Common close button selectors
        close_selectors = [
            "button.close-icon", 
            "button[aria-label='Close']", 
            "[data-testid='close-button']",
            ".close-button",
            "button:has-text('×')"
        ]
        
        # Check for the specific "Never miss..." promo text
        promo_text = "Never miss a market-moving event"
        promo_locator = page.locator(f"text='{promo_text}'")
        if promo_locator.is_visible(timeout=500):
            # Try to find a close button near this text or globally
            # First try common selectors
            for sel in close_selectors:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=200):
                    btn.click()
                    return True

            # Fallback: look for any visible button whose aria-label or text contains 'close'
            try:
                for b in page.locator('button').all():
                    try:
                        a = (b.get_attribute('aria-label') or '').lower()
                        t = (b.text_content() or '').strip().lower()
                        if 'close' in a or 'close' in t or t == '×' or 'close tour' in a or 'close tour' in t:
                            b.click()
                            return True
                    except:
                        continue
            except:
                pass
    except:
        pass
    return False


def extract_from_page(page_obj):
    """Robustly extract article-like text from a Playwright Page object."""
    content_selectors = [
        "article",
        ".article-body",
        ".news-article",
        ".main-content",
        ".content-body",
        ".news-detail-content",
    ]

    try:
        # Wait for typical article containers to appear
        page_obj.wait_for_selector(
            ", ".join(content_selectors),
            timeout=8000,
        )
    except:
        # ignore timeout, we'll fallback to body extraction
        pass

    for sel in content_selectors:
        try:
            el = page_obj.locator(sel).first
            if el.count() > 0:
                txt = el.inner_text().strip()
                if len(txt) > 100:
                    return txt
        except:
            continue

    # Final fallback: take all innerText of body but strip scripts/styles/nav/header/footer
    try:
        body_text = page_obj.evaluate("""() => {
            const body = document.body.cloneNode(true);
            ['script', 'style', 'nav', 'header', 'footer', 'promo'].forEach(tag => {
                body.querySelectorAll(tag).forEach(el => el.remove());
            });
            return body.innerText.trim();
        }""")
        return body_text
    except:
        return ""


def extract_from_locator(locator):
    """Extract article-like text from a modal Locator."""
    content_selectors = [
        ".news-detail-content",
        ".article-content",
        ".ig-news_detail_content",
        ".article-body",
        ".news-body",
        "article",
    ]

    for sel in content_selectors:
        try:
            els = locator.locator(sel).all()
            for el in els:
                if el.is_visible():
                    txt = el.inner_text().strip()
                    if len(txt) > 50 and "Never miss a market-moving event" not in txt[:100]:
                        return txt
        except:
            continue

    try:
        # Last resort: return the locator's inner text (clean promo)
        txt = locator.inner_text().strip()
        promo_pattern = r"Never miss a market-moving event.*?trading experience\."
        txt = re.sub(promo_pattern, "", txt, flags=re.DOTALL | re.IGNORECASE).strip()
        return txt
    except:
        return ""


def scrape_news_for_instrument(page, instrument: str, MAX_NEWS_ITEMS=2) -> list[dict]:
    """Scrape news items for a specific instrument."""
    logger.info(f"Searching news for: {instrument}")
    
    # Click Search tab to start a new search
    try:
        # Sometimes search tab needs to be clicked again or it is already active
        page.get_by_role("listitem").filter(has_text="Search").locator("span").click()
    except:
        pass
    page.wait_for_timeout(1000)
    
    # Fill the search box with the instrument name
    search_box = page.get_by_role("textbox", name="Search by market name,")
    search_box.fill("")
    page.wait_for_timeout(300)
    search_box.fill(instrument)
    search_box.press("Enter")
    
    # Wait for search results to load
    page.wait_for_timeout(3000)
    
    news_items = []
    
    # Regex to find dates like "07 Feb", "7 Feb", "07 Feb 2024", "07-Feb", "07/02/2026"
    # Matches: DD Mon, DD-Mon, DD/MM/YYYY
    date_pattern = re.compile(r"(\d{1,2}\s*[./-]?\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*(?:[\'’]?\d{2,4})?)", re.IGNORECASE)
    # Also DD/MM/YYYY
    date_pattern_numeric = re.compile(r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})")

    # Iterate through potential news items
    for i in range(MAX_NEWS_ITEMS):
        try:
            close_popups(page)
            
            # Re-query headlines every time to handle DOM updates
            headlines = page.locator(".ig-news_headline").all()
            
            if i >= len(headlines):
                # Try scrolling if we ran out of visible items
                page.evaluate("window.scrollBy(0, 500)")
                page.wait_for_timeout(2000)
                headlines = page.locator(".ig-news_headline").all()
                if i >= len(headlines):
                    logger.info(f"  No more items found after {i} items")
                    break
            
            headline_el = headlines[i]
            headline_el.scroll_into_view_if_needed()
            
            # Get headline text
            headline = headline_el.get_attribute("title") or headline_el.text_content()
            if headline:
                headline = headline.strip()
            
            # Initial attempt to get date from list row (backup) using Regex on row text
            list_date = ""
            try:
                # Use JS to get text of the parent row to be robust
                row_text = headline_el.evaluate("el => el.closest('.ig-news_row')?.innerText || el.parentElement.innerText")
                if row_text:
                    # Check if first line is a time (HH:MM) - means it's today's news
                    first_line = row_text.split('\n')[0].strip() if row_text else ""
                    time_match = re.match(r"^(\d{1,2}:\d{2})$", first_line)
                    if time_match:
                        # It's a time, so news is from today
                        list_date = datetime.now().strftime("%d %b %Y")
                    else:
                        match = date_pattern.search(row_text)
                        if match:
                            list_date = match.group(1).strip()
                        else:
                             match_num = date_pattern_numeric.search(row_text)
                             if match_num:
                                 list_date = match_num.group(1).strip()
            except Exception as e:
                pass

            # First, try to find a row-level 'Open in new window' popout button (works without opening modal)
            row_popout_clicked = False
            try:
                row_locator = headline_el.locator("xpath=ancestor::div[contains(@class,'ig-news_row')][1]")
                cnt = 0
                try:
                    cnt = row_locator.count()
                except:
                    cnt = 0
                logger.debug(f"  row_locator count = {cnt}")
                if cnt > 0:
                    popout_selectors_row = [
                        "button:has-text('Open in new window')",
                        "a:has-text('Open in new window')",
                        ".ig-news-article-header_popout",
                        "button.ig-news-article-header_new-window"
                    ]
                    for sel in popout_selectors_row:
                        try:
                            btn = row_locator.locator(sel).first
                            if btn.is_visible(timeout=800):
                                logger.debug(f"  found row popout button with selector: {sel}")
                                with page.context.expect_page(timeout=10000) as new_page_info:
                                    btn.click()
                                new_page = new_page_info.value
                                new_page.wait_for_load_state('domcontentloaded')
                                link = new_page.url
                                detail_text = extract_from_page(new_page) or ""
                                logger.debug(f"  extracted popout text length={len(detail_text)} preview=\n{(detail_text[:300] or '(empty)')}\n---")
                                new_page.close()
                                row_popout_clicked = True
                                break
                        except:
                            continue
            except:
                pass

            # If row-level popout didn't open, click headline to open detail modal/panel
            if not row_popout_clicked:
                headline_el.click(force=True)
            
            # Wait for detail view to appear
            modal_selector = "[role='dialog'], [aria-modal='true'], .ig-news_detail, .news-detail, [class*='Modal'], [class*='Drawer'], [class*='SidePanel'], .ig-news_row-expanded"
            
            modal_found = False
            detail_text_debug = ""
            link = ""
            detail_date = ""
            modal = None
            extracted_via_popout = False
            
            # Try to find the visible modal for a few seconds
            # After opening the item (headline click), sometimes a global 'Open in new window' button appears
            # Try to detect a global popout control before searching for modal/detail containers
            try:
                for _g in range(6):
                    popout_global = None
                    try:
                        popout_global = page.locator("button:has-text('Open in new window'), a:has-text('Open in new window'), button.ig-news-article-header_new-window").first
                    except:
                        popout_global = None
                    if popout_global:
                        try:
                            if popout_global.is_visible(timeout=500):
                                logger.debug("  found global popout button after clicking headline")
                                with page.context.expect_page(timeout=10000) as new_page_info:
                                    popout_global.click()
                                new_page = new_page_info.value
                                new_page.wait_for_load_state('domcontentloaded')
                                link = new_page.url
                                detail_text = extract_from_page(new_page) or ""
                                logger.debug(f"  extracted popout text length={len(detail_text)} preview=\n{(detail_text[:300] or '(empty)')}\n---")
                                new_page.close()
                                # We got content; mark and skip modal logic
                                extracted_via_popout = True
                                modal_found = False
                                modal = None
                                break
                        except:
                            pass
                    page.wait_for_timeout(300)
            except:
                pass

            # Try to find the visible modal for a few seconds
            try:
                sample_modals = page.locator(modal_selector).all()
                logger.debug(f"  initial modal_selector matched {len(sample_modals)} elements")
            except:
                logger.debug("  modal_selector query failed")
            for _ in range(8):
                all_modals = page.locator(modal_selector).all()
                for idx_m, m in enumerate(all_modals):
                    try:
                        # print a short preview for debugging
                        preview = (m.inner_text() or "").strip()[:200]
                    except:
                        preview = "(no preview)"
                    # logger.debug(f"    modal[{idx_m}] preview={preview}")
                    if m.is_visible():
                        modal = m
                        modal_found = True
                        break
                if modal_found:
                    break
                page.wait_for_timeout(500)
            
            if extracted_via_popout:
                # Content was already extracted via popout/global popout; use that
                detail_text_debug = detail_text or "Content not found"
            elif modal_found:
                # Be careful not to close the news modal itself
                # Only call close_popups if we see the specific promo text
                promo_text = "Never miss a market-moving event"
                if page.locator(f"text='{promo_text}'").is_visible(timeout=500):
                    close_popups(page)
                
                detail_text = ""
                link = ""

                # Debug: log modal text length and candidate controls to diagnose extraction issues
                try:
                    modal_text = modal.inner_text().strip()[:1200]
                except:
                    modal_text = "(could not read modal inner_text)"
                logger.debug(f"  modal found. modal_text[:1200]=\n{modal_text}\n---")
                try:
                    controls = modal.locator("a, button").all()
                    logger.debug(f"  modal has {len(controls)} anchors/buttons (showing up to 20):")
                    for idx, c in enumerate(controls[:20]):
                        try:
                            txt = (c.text_content() or "").strip().replace('\n', ' ')[:80]
                            href = c.get_attribute('href') or ''
                            aria = c.get_attribute('aria-label') or ''
                            title = c.get_attribute('title') or ''
                            logger.debug(f"    - [{idx}] text='{txt}' href='{href}' aria-label='{aria}' title='{title}'")
                        except:
                            logger.debug(f"    - [{idx}] (could not read control properties)")
                except:
                    logger.debug("  failed to enumerate modal controls")

                # If this modal is only the promo overlay, try to close it and re-find the real news modal
                promo_text = "Never miss a market-moving event"
                if promo_text.lower() in modal_text.lower():
                    logger.debug("  promo modal detected inside modal. Attempting to close...")
                    closed = False
                    # Try closing via page-level helper first
                    try:
                        closed = close_popups(page)
                    except:
                        closed = False

                    # If that failed, try to click a close button inside the modal itself
                    if not closed:
                        try:
                            for b in modal.locator('button').all():
                                try:
                                    a = (b.get_attribute('aria-label') or '').lower()
                                    t = (b.text_content() or '').strip().lower()
                                    if 'close' in a or 'close' in t or t == '×' or 'close tour' in a or 'close tour' in t:
                                        try:
                                            b.click(force=True)
                                            closed = True
                                            logger.debug('  clicked close button inside modal (force)')
                                            break
                                        except Exception as e:
                                            logger.debug(f"  click failed: {e}; trying Escape key")
                                            try:
                                                page.keyboard.press('Escape')
                                                closed = True
                                                logger.debug('  pressed Escape to close modal')
                                                break
                                            except:
                                                continue
                                except:
                                    continue
                        except:
                            pass
                    if closed:
                        # Give the page a moment then try to find the actual news modal
                        page.wait_for_timeout(800)
                        modal_found = False
                        modal = None
                        for _r in range(6):
                            all_modals2 = page.locator(modal_selector).all()
                            for m2 in all_modals2:
                                try:
                                    if not m2.is_visible():
                                        continue
                                    txt2 = (m2.inner_text() or "").strip()[:500]
                                    if promo_text.lower() in txt2.lower():
                                        continue
                                    modal = m2
                                    modal_found = True
                                    break
                                except:
                                    continue
                            if modal_found:
                                logger.debug("  real news modal found after closing promo")
                                break
                            page.wait_for_timeout(300)
                    # If we couldn't find a non-promo modal after closing, skip this item
                    if not modal_found:
                        logger.debug("  no article modal found after closing promo; skipping item")
                        # ensure modal is None to avoid using stale reference
                        modal = None
                        continue

                # Try to open in new window for better content and link extraction
                try:
                    # Selectors for 'Open in new window' button
                    popout_selectors = [
                        "button.ig-news-article-header_new-window",
                        "button:has-text('Open in new window')",
                        "a:has-text('Open in new window')",
                        ".ig-news-article-header_popout"
                    ]
                    
                    popout_btn = None
                    for sel in popout_selectors:
                        btn = modal.locator(sel).first
                        if btn.is_visible(timeout=1000):
                            popout_btn = btn
                            # logger.debug(f"  Popout button found with selector: {sel}")
                            break
                    
                    if not popout_btn:
                        # Fallback to get_by_role
                        btn = modal.get_by_role("button", name="Open in new window").first
                        if btn.is_visible(timeout=500):
                            popout_btn = btn
                            # logger.debug("  Popout button found with get_by_role")
                    
                    if popout_btn:
                        # Expect a new page to open
                        with page.context.expect_page(timeout=10000) as new_page_info:
                            popout_btn.click()
                        new_page = new_page_info.value
                        new_page.wait_for_load_state("domcontentloaded")
                        # logger.debug(f"  Popout page opened: {new_page.url}")
                        
                        # IMPORTANT: Wait for the network to be idle or specific selectors 
                        # to ensure the dynamic content has loaded.
                        try:
                            # Wait for the article body to appear
                            new_page.wait_for_selector("article, .article-body, .news-article, div.content, .main-content", timeout=10000)
                        except:
                            # Fallback to a plain wait if selector not found
                            new_page.wait_for_timeout(3000)
                        
                        # Get correct URL (the actual article source)
                        link = new_page.url
                        # Extract content using robust helper
                        try:
                            detail_text = extract_from_page(new_page) or ""
                        except:
                            detail_text = ""
                        new_page.close()
                except Exception as e:
                    # logger.debug(f"  New window strategy failed: {e}")
                    pass

                # Fallback link extraction from modal
                if not link or link == "Link not found":
                    found_link = ""
                    for l in modal.locator("a").all():
                        href = l.get_attribute("href") or ""
                        text = (l.text_content() or "").strip().lower()
                        if any(x in href.lower() for x in ["crypto-risks", "terms", "privacy", "cookie", "legal"]): continue
                        if not href.startswith("http"): continue
                        if any(x in text for x in ["open in new window", "read full story", "full article", "view full", "source"]):
                            found_link = href
                            break
                        if l.get_attribute("target") == "_blank" and not found_link: found_link = href
                    link = found_link
                
                # Fallback text content extraction from modal (use helper)
                if not detail_text or detail_text == "Content not found":
                    try:
                        detail_text = extract_from_locator(modal) or ""
                    except:
                        detail_text = ""
                
                # If we failed to extract from popout/modal but have a link, try opening the link directly
                try:
                    if (not detail_text or len(detail_text) < 100) and link and link.startswith('http'):
                        logger.debug(f"  attempting direct navigation to link: {link}")
                        try:
                            extra_page = page.context.new_page()
                            extra_page.goto(link, timeout=15000)
                            try:
                                extra_page.wait_for_selector("article, .article-body, .news-article, div.content, .main-content", timeout=10000)
                            except:
                                extra_page.wait_for_timeout(3000)
                            extracted = extract_from_page(extra_page) or ""
                            if extracted and len(extracted) > len(detail_text or ""):
                                detail_text = extracted
                                logger.debug("  extracted content from direct link")
                            extra_page.close()
                        except Exception as e:
                            logger.debug(f"  direct link extraction failed: {e}")
                except:
                    pass

                detail_text_debug = detail_text

                # Date handling
                today_str = datetime.now().strftime("%d %b %Y")
                yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%d %b %Y")
                if "today" in detail_text.lower(): detail_date = today_str
                elif "yesterday" in detail_text.lower(): detail_date = yesterday_str
                else:
                    match = date_pattern.search(detail_text) or date_pattern_numeric.search(detail_text)
                    if match:
                        detail_date = match.group(1).strip()
                        if not re.search(r"\d{4}|\s\'\d{2}$", detail_date):
                            detail_date += f" {datetime.now().year}"
            else:
                # Modal not found, fallback to page content if we think it might be there
                # sometimes news just expands in place or uses a weird container
                detail_text_debug = "Could not locate news detail modal/panel."
            
            # Close the detail view
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                
                # If close button is still visible, click it (modal didn't close with escape?)
                close_btn = page.locator("button[aria-label='Close'], [data-testid='close-button'], button.close-icon").first
                if close_btn.is_visible(timeout=500):
                    close_btn.click()
            except:
                pass
                
            page.wait_for_timeout(500)
            
            # Finalize data
            final_date = detail_date if detail_date else list_date
            if not final_date: final_date = "Date not found"

            news_items.append({
                "date": final_date,
                "headline": headline,
                "link": link or "Link not found",
                "content": detail_text_debug or "Content not found"
            })
            logger.info(f"  [{len(news_items)}] {headline[:40]}... | Date: {final_date} | Link found: {'Yes' if link else 'No'}")
            
        except Exception as e:
            logger.error(f"  Error processing item {i}: {e}")
            # Try to recover by pressing Escape just in case we are stuck in a modal
            try:
                page.keyboard.press("Escape")
            except:
                pass
            continue
    
    logger.info(f"Collected {len(news_items)} news items for {instrument}")
    return news_items


def load_existing_headlines(csv_path: str) -> set[str]:
    """Load existing headlines from a CSV file into a set for deduplication."""
    headlines = set()
    if os.path.isfile(csv_path):
        try:
            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    h = row.get("headline", "").strip()
                    if h:
                        headlines.add(h)
            logger.info(f"Loaded {len(headlines)} existing headlines from {csv_path}")
        except Exception as e:
            logger.warning(f"Could not read existing CSV {csv_path}: {e}")
    return headlines


def save_to_csv(news_items: list[dict], instrument: str, output_dir: str):
    """Save news items to a CSV file. Appends if the file already exists.
    
    Caller is responsible for deduplication — only pass new items.
    """
    filename = os.path.join(output_dir, f"ig.news.{instrument}.csv")
    file_exists = os.path.isfile(filename)
    with open(filename, "a" if file_exists else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "headline", "link"])
        if not file_exists:
            writer.writeheader()
        csv_items = [{"date": i["date"], "headline": i["headline"], "link": i["link"]} for i in news_items]
        writer.writerows(csv_items)
    logger.info(f"Appended {len(news_items)} new items to {filename}")


def save_to_markdown(news_items: list[dict], instrument: str, output_dir: str):
    """Save news items to a Markdown file. Appends if the file already exists.
    
    Caller is responsible for deduplication — only pass new items.
    """
    filename = os.path.join(output_dir, f"ig.news.{instrument}.md")
    file_exists = os.path.isfile(filename)
    with open(filename, "a" if file_exists else "w", encoding="utf-8") as f:
        if not file_exists:
            f.write(f"# News for {instrument.capitalize()}\n\n")
            f.write(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")
        else:
            f.write(f"\n## — Updated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} —\n\n")

        for item in news_items:
            f.write(f"## {item['headline']}\n\n")
            f.write(f"- **Date:** {item['date']}\n")
            f.write(f"- **Source Link:** {item['link']}\n\n")
            f.write("### Content\n\n")
            f.write(f"{item['content']}\n\n")
            f.write("---\n\n")
    logger.info(f"Appended {len(news_items)} new items to {filename}")


def scrape_open_positions(page) -> list[str]:
    """Navigate to Positions tab and scrape all instrument names.

    Returns a deduplicated list of instrument names with trailing
    qualifiers like ' (24 Hours)' stripped.
    """
    logger.info("Scraping open positions to build instrument list...")

    # Click on the Positions tab
    try:
        page.get_by_role("button", name="Positions").click()
        page.wait_for_timeout(5000)  # wait for position rows to load
    except Exception as e:
        logger.error(f"Could not navigate to Positions tab: {e}")
        return []

    instruments: list[str] = []
    try:
        name_elements = page.locator('[data-automation="instrumentName"]').all()
        for el in name_elements:
            try:
                raw_name = (el.inner_text() or "").strip()
                if not raw_name:
                    continue
                # Strip common trailing qualifiers like " (24 Hours)"
                clean_name = re.sub(r"\s*\(.*?\)\s*$", "", raw_name).strip()
                if clean_name and clean_name not in instruments:
                    instruments.append(clean_name)
            except Exception:
                continue
    except Exception as e:
        logger.error(f"Failed to extract instrument names from Positions: {e}")

    logger.info(f"Found {len(instruments)} instruments from open positions: {instruments}")
    return instruments


def run(playwright: Playwright, username, password, INSTRUMENTS, output_dir, MAX_NEWS_ITEMS = 5, headless=False
) -> None:
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Configuration
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.ig.com/uk")
    page.wait_for_timeout(5000)
    if page.get_by_role("button", name="Accept").is_visible():
        page.get_by_role("button", name="Accept").click()
    page.get_by_role("link", name="Log in").click()
    if page.get_by_role("button", name="Accept").is_visible():
        page.get_by_role("button", name="Accept").click()
    page.get_by_role("textbox", name="Email/username").click()
    page.get_by_role("textbox", name="Email/username").fill(username)
    page.get_by_role("textbox", name="Email/username").press("Tab")
    page.get_by_role("textbox", name="Password").fill(password)
    page.get_by_role("button", name="Log in").click()
    
    try: 
        expect(page.get_by_role("button", name="Open platform").first).to_be_visible(timeout=10000)
    except Exception:
        logger.error("Login failed or platform dashboard not loaded properly")
        context.close()
        browser.close()
        sys.exit(1)

    page.get_by_role("button", name="Open platform").first.click()
    
    # Wait for platform to fully load
    page.wait_for_timeout(15000)
    

    # Scrape open positions if INSTRUMENTS is None (no --input provided)
    if INSTRUMENTS is None:
        INSTRUMENTS = []
        try:
            INSTRUMENTS = scrape_open_positions(page)
            logger.info(f"Total instruments from open positions: {len(INSTRUMENTS)}")
        except Exception as e:
            logger.error(f"Failed to scrape/add open positions: {e}")
        if not INSTRUMENTS:
            logger.error("No instruments found from positions and no --input provided. Exiting.")
            context.close()
            browser.close()
            sys.exit(1)


    # Navigate to News section once (using the original selector that worked)
    page.get_by_title("News").click()
    page.wait_for_timeout(2000)
    
    # Scrape news for each instrument
    total_instruments = len(INSTRUMENTS)
    for idx, instrument in enumerate(INSTRUMENTS):
        try:
            news_items = scrape_news_for_instrument(page, instrument, MAX_NEWS_ITEMS)
            if news_items:
                # Load existing headlines once to use for both CSV and MD dedup
                csv_path = os.path.join(output_dir, f"ig.news.{instrument}.csv")
                existing_headlines = load_existing_headlines(csv_path)
                new_items = [i for i in news_items if i["headline"].strip() not in existing_headlines]

                if new_items:
                    logger.info(f"{len(new_items)} new items for {instrument} (out of {len(news_items)} scraped)")
                    save_to_csv(new_items, instrument, output_dir)
                    save_to_markdown(new_items, instrument, output_dir)
                else:
                    logger.info(f"All {len(news_items)} scraped headlines for {instrument} already exist — skipping save")
            else:
                logger.info(f"No news items found for {instrument}")
            
            remaining = total_instruments - (idx + 1)
            logger.info(f"All headlines for {instrument} collected, {remaining} more instruments to go")
        except Exception as e:
            logger.error(f"Error scraping news for {instrument}: {e}")
            remaining = total_instruments - (idx + 1)
            logger.info(f"Finished Attempt for {instrument}, {remaining} more instruments to go")
            continue

    # ---------------------
    context.close()
    browser.close()
    logger.info("Done!")

def main():
    parser = argparse.ArgumentParser(description="Scrape IG News", epilog=
                                     "Example usage:\n"
        "  python ig.news.py --username your_ig_username --password your_ig_password --input company_names.txt --output ./news_output\n\n"
        "Input file can be a .txt (one company name per line), .csv (first column as company names), or .json (keys as company names).")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument(
        "-u", "--username", type=str, default="shanghailondon2000", help="IG account username"
    )
    parser.add_argument(
        "-p", "--password", type=str, help="IG account password"
    )
    parser.add_argument(
        "--output", type=str, default=".", help="Directory to save output files"
    )
    parser.add_argument(
        "--input", type=str, help="Path to input file with company names or search terms (one per line)"
    )
    parser.add_argument(
        "--max-news-items", type=int, default=5, help="Maximum number of news items to scrape per instrument"
    )
    args = parser.parse_args()

    username = args.username
    password = args.password
    if not password:
        logger.error("Missing password. Use --password to provide it.")
        sys.exit(1)
    output_dir = args.output
    input_file = args.input
    if input_file is None:
        # No input file — instruments will be scraped from open positions
        company_names = None
        logger.info("No --input provided; will scrape instruments from IG open positions.")
    elif not os.path.isfile(input_file):
        logger.error(f"Input file not found: {input_file}")
        sys.exit(1)
    elif input_file.endswith(".json"):
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        company_names = [" ".join(k.split()[:2]) for k in data.keys()]
    elif input_file.endswith(".csv"):
        company_names = []
        with open(input_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header row
            for row in reader:
                if row:
                    company_names.append(row[0].strip())
    else:
        try:
            with open(input_file, "r", encoding="utf-8") as f:
                company_names = [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.error(f"Failed to read input file: {e}")
            sys.exit(1)

    max_news_items = args.max_news_items


    with sync_playwright() as playwright:
        run(playwright, 
            username=username,
            password=password, 
            INSTRUMENTS=company_names,
            output_dir=output_dir,
            MAX_NEWS_ITEMS=max_news_items, 
            headless=args.headless)
        
if __name__ == "__main__":
    startime = datetime.now()
    logger.info(f"Script started at {startime.strftime('%Y-%m-%d %H:%M:%S')}")
    main()
    endtime = datetime.now()
    duration = endtime - startime
    logger.info(f"Script finished at {endtime.strftime('%Y-%m-%d %H:%M:%S')}, duration: {duration}")