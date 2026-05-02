import argparse
import getpass
import os
import sys
from datetime import datetime
from typing import Optional
from playwright.sync_api import Playwright, sync_playwright, expect, Page


def set_date_picker_value(page: Page, date_str: str):
    """
    Set date picker value directly via JavaScript.
    
    Args:
        page: Playwright page object
        date_str: Date in DD/MM/YYYY format (e.g., "01/01/2018")
    """
    # Parse the date string
    day, month, year = date_str.split('/')
    
    # Resolve Pylante complaint: tuple of pairs (ordered, hashable)
    date_key = (('day', day), ('month', month), ('year', year), ('formatted', date_str))
    
    # Use JavaScript to find and set the date input value
    # Normalize dateInfo if Playwright serializes the tuple as an array of pairs
    page.evaluate("""
        (dateInfo) => {
            const info = Array.isArray(dateInfo) ? Object.fromEntries(dateInfo) : dateInfo;
            // Find date/text inputs in the date picker area
            const inputs = document.querySelectorAll('input[type="text"], input[type="date"], input[data-testid*="date" i]');
            inputs.forEach(input => {
                // Set the value
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(input, info.formatted);
                
                // Dispatch events to trigger React/framework updates
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            });
        }
    """, date_key)


def navigate_to_date_and_select(page: Page, date_str: str):
    """
    Navigate date picker to specific date using keyboard/fill approach.
    
    Args:
        page: Playwright page object  
        date_str: Date in DD/MM/YYYY format (e.g., "01/01/2018")
    """
    day, month, year = date_str.split('/')
    target_year = int(year)
    target_day = int(day)
    current_year = datetime.now().year
    
    # Calculate years to go back
    years_back = current_year - target_year
    
    # Try to find and fill any visible date input first
    date_inputs = page.locator('input[type="text"]').all()
    for inp in date_inputs:
        if inp.is_visible():
            try:
                inp.fill(date_str)
                inp.press('Enter')
                page.wait_for_timeout(500)
                return True
            except Exception:
                pass
    
    # Fallback: use calculated clicks for year navigation
    for _ in range(years_back):
        page.get_by_test_id("IconButtonPrevYear").click()
        page.wait_for_timeout(100)  # Small delay between clicks
    
    # Click the day
    page.get_by_role("button", name=f"{target_day:02d}").click()
    return True


def run(
    playwright: Playwright,
    username: str,
    passwd: str,
    download_both: bool = False,
    download_dir: Optional[str] = None,
    start_date: str = "01/01/2018",
):
    def dismiss_onetrust(p: Page):
        """Remove OneTrust cookie/privacy overlay — tries button click then JS removal."""
        for selector in (
            "#onetrust-accept-btn-handler",
            "button#accept-recommended-btn-handler",
        ):
            try:
                btn = p.locator(selector)
                if btn.count() > 0 and btn.is_visible(timeout=1000):
                    btn.click()
                    p.wait_for_timeout(600)
                    return
            except Exception:
                pass
        for label in ("Accept all cookies", "Accept All Cookies", "Accept all", "Accept"):
            try:
                btn = p.locator(f'button:has-text("{label}")')
                if btn.count() > 0 and btn.first.is_visible(timeout=500):
                    btn.first.click()
                    p.wait_for_timeout(600)
                    return
            except Exception:
                pass
        # Force-remove via JS as last resort
        p.evaluate("""() => {
            ['#onetrust-consent-sdk', '.onetrust-pc-dark-filter',
             '#onetrust-pc-sdk', '#onetrust-banner-sdk'].forEach(sel => {
                const el = document.querySelector(sel);
                if (el) el.remove();
            });
            document.body.style.overflow = '';
        }""")
        p.wait_for_timeout(300)

    downloaded_files = []
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.ig.com/uk")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    dismiss_onetrust(page)
    page.get_by_role("link", name="Log in").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    dismiss_onetrust(page)
    page.get_by_role("textbox", name="Email/username").fill(username)
    page.get_by_role("textbox", name="Email/username").press("Tab")
    page.get_by_role("textbox", name="Password").fill(passwd)
    dismiss_onetrust(page)
    page.get_by_role("button", name="Log in").click()
    # Wait for dashboard to fully load — spinner disappears, Open platform appears
    print(f"[DEBUG] Waiting for dashboard after login...", file=sys.stderr)
    try:
        # Wait up to 20s for any "Open platform" button to appear
        page.get_by_role("button", name="Open platform").first.wait_for(timeout=20000)
    except Exception as e:
        page.screenshot(path="/tmp/ig_debug_login.png")
        print(f"[DEBUG] URL: {page.url}, title: {page.title()}", file=sys.stderr)
        print(f"[DEBUG] Screenshot: /tmp/ig_debug_login.png", file=sys.stderr)
        print(f"Login failed — could not find 'Open platform' button: {e}", file=sys.stderr)
        context.close()
        browser.close()
        sys.exit(1)
    all_btns = page.get_by_role("button", name="Open platform").all()
    print(f"[DEBUG] URL: {page.url} — 'Open platform' buttons: {len(all_btns)}", file=sys.stderr)
    # Use nth(1) for the second button (ISA platform)
    isa_btn = page.get_by_role("button", name="Open platform").nth(1)
    if not isa_btn.is_visible():
        print("[DEBUG] Second 'Open platform' not visible, falling back to first", file=sys.stderr)
        isa_btn = page.get_by_role("button", name="Open platform").first
    isa_btn.click()
    print(f"[DEBUG] Clicked ISA 'Open platform'", file=sys.stderr)
    # Platform may open in a new tab — poll for up to 5s
    for _ in range(10):
        page.wait_for_timeout(500)
        if len(context.pages) > 1:
            break
    if len(context.pages) > 1:
        page = context.pages[-1]
        print(f"[DEBUG] Switched to new tab — URL: {page.url}", file=sys.stderr)
    else:
        print(f"[DEBUG] Same tab — URL: {page.url}", file=sys.stderr)
    # SPA never reaches networkidle — wait for the History button to appear instead
    try:
        page.get_by_role("button", name="History").wait_for(timeout=30000)
    except Exception:
        page.screenshot(path="/tmp/ig_debug_platform.png")
        print(f"[DEBUG] Platform screenshot: /tmp/ig_debug_platform.png — URL: {page.url}", file=sys.stderr)
        raise
    page.get_by_role("button", name="History").click()
    print("[DEBUG] Clicked History button", file=sys.stderr)
    # View full history may open a new tab
    pages_before = len(context.pages)
    page.get_by_role("link", name="View full history in My IG").click()
    page.wait_for_timeout(3000)
    if len(context.pages) > pages_before:
        page = context.pages[-1]
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        print(f"[DEBUG] Switched to My IG tab — URL: {page.url}", file=sys.stderr)


    if download_both:
        page.get_by_test_id("DateRangeSelectWrapper").locator("svg").click()
        page.get_by_text("Custom period", exact=True).click()
        page.wait_for_timeout(500)  # Wait for date picker to open
        navigate_to_date_and_select(page, start_date)
        page.get_by_role("button", name="Set").click()
        page.get_by_test_id("ShowHistoryButton").click()
        try:
            with page.expect_download() as download_info:
                page.get_by_test_id("DownloadHistoryButton").click()
            download = download_info.value
            # default Downloads location unless overridden by --download-dir
            if download_dir:
                download_path = os.path.join(download_dir, download.suggested_filename)
            else:
                download_path = os.path.expanduser(f"~/Downloads/{download.suggested_filename}")
            download.save_as(download_path)
            print(f"Trade history downloaded to: {download_path}")
            downloaded_files.append(download_path)
        except Exception as exc:
            print(f"Trade history download failed: {exc}", file=sys.stderr)
    
    else:
        print("Skipping transaction history download")
    
    page.get_by_test_id("trade-history").click()
    page.get_by_test_id("SelectSingleValue").click()
    page.get_by_text("Custom period", exact=True).click()
    page.wait_for_timeout(500)  # Wait for date picker to open
    navigate_to_date_and_select(page, start_date)
    page.get_by_role("button", name="Set").click()
    page.get_by_test_id("ShowHistoryButton").click()
    try:
        with page.expect_download() as download1_info:
            page.get_by_test_id("DownloadHistoryButton").click()
        download1 = download1_info.value
        if download_dir:
            download1_path = os.path.join(download_dir, download1.suggested_filename)
        else:
            download1_path = os.path.expanduser(f"~/Downloads/{download1.suggested_filename}")
        download1.save_as(download1_path)
        print(f"Transaction history downloaded to: {download1_path}")
        downloaded_files.append(download1_path)
    except Exception as exc:
        print(f"Transaction history download failed: {exc}", file=sys.stderr)
    # ---------------------
    context.close()
    browser.close()
    return downloaded_files


def main():
    # Load .env file automatically if it exists
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    key, val = line.strip().split('=', 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")

    parser = argparse.ArgumentParser(
        description="Download IG trade history and transactions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --username myusername --password mypassword --download-dir /path/to/save/downloads --skip-transactions
    %(prog)s  # Will prompt for username and password securely
        """,
    )
    parser.add_argument(
        "-u", "--username",
        type=str,
        help="IG account username (will prompt if not provided)",
    )
    parser.add_argument(
        "-p", "--password",
        type=str,
        help="IG account password (will prompt if not provided)",
    )
    parser.add_argument(
        "--skip-transactions",
        action="store_true",
        help="Only download trade history, skip the transactions flow",
    )
    parser.add_argument(
        "--download-dir",
        type=str,
        help="Optional directory to save downloads into (default is ~/Downloads/)",
    )
    args = parser.parse_args()

    username = args.username or os.environ.get("IG_USERNAME")
    if not username:
        username = input("Enter IG login username: ")
    password = args.password or os.environ.get("IG_PASSWORD")
    if not password:
        password = getpass.getpass("Enter IG login password: ")
    if not password:
        print("Error: Password is required", file=sys.stderr)
        sys.exit(1)


    with sync_playwright() as playwright:
        download_dir_value = None
        if hasattr(args, "download_dir") and args.download_dir:
            download_dir_value = os.path.expanduser(args.download_dir)
            # ensure directory exists
            os.makedirs(download_dir_value, exist_ok=True)
        saved_files = run(playwright, username, password, download_both=not args.skip_transactions, download_dir=download_dir_value)

        if saved_files:
            print(f"\nAll files saved successfully:")
            for f in saved_files:
                print(f" - {f}")


if __name__ == "__main__":
    main()