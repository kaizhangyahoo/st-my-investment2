import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://consent.google.com/m?continue=https://finance.google.com/&gl=GB&m=0&pc=fgc&cm=2&hl=en-US&src=1")
    page.get_by_role("button", name="Accept all").click()
    page.get_by_role("combobox", name="Search for stocks, ETFs & more").click()
    page.get_by_role("combobox", name="Search for stocks, ETFs & more").fill("solventum corp")
    page.get_by_role("combobox", name="Search for stocks, ETFs & more").press("Enter")
    page.get_by_role("heading", name="In the news").click()
    with page.expect_popup() as page1_info:
        page.get_by_role("link", name="MarketBeat •  1 week ago What").click()
    page1 = page1_info.value
    page.get_by_role("combobox", name="Search for stocks, ETFs & more").click()
    page.get_by_role("combobox", name="Search for stocks, ETFs & more").fill("rtx corporation")
    page.get_by_role("combobox", name="Search for stocks, ETFs & more").press("Enter")
    page.get_by_role("heading", name="In the news").click()
    with page.expect_popup() as page2_info:
        page.get_by_role("link", name="TradingView •  1 day ago Key").click()
    page2 = page2_info.value

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
