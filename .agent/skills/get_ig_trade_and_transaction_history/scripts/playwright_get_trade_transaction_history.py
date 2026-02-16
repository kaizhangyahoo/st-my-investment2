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
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.ig.com/uk")
    page.get_by_role("button", name="Accept").click()
    page.get_by_role("link", name="Log in").click()
    page.get_by_role("textbox", name="Email/username").fill(username)
    page.get_by_role("textbox", name="Email/username").press("Tab")
    page.get_by_role("textbox", name="Password").fill(passwd)
    page.get_by_role("button", name="Log in").click()
    # check if login was successful
    try: 
        expect(page.get_by_role("button", name="Open platform").first).to_be_visible(timeout=10000)
    except Exception:
        print("Login failed or platform dashboard not loaded properly", file=sys.stderr)
        context.close()
        browser.close()
        sys.exit(1)
    page.get_by_role("button", name="Open platform").first.click()
    page.get_by_role("button", name="History").click()
    page.get_by_role("link", name="View full history in My IG").click()


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
            saved = download_path
        except Exception as exc:
            print(f"Trade history download failed: {exc}", file=sys.stderr)
            saved = None
    
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
        saved1 = download1_path
    except Exception as exc:
        print(f"Transaction history download failed: {exc}", file=sys.stderr)
        saved1 = None
    # ---------------------
    context.close()
    browser.close()


def main():
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

    username = args.username
    if not username:
        username = input("Enter IG login username: ")
    password = args.password
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
        run(playwright, username, password, download_both=not args.skip_transactions, download_dir=download_dir_value)


if __name__ == "__main__":
    main()