# Archive

This directory contains legacy/unused scripts and alternate variants that are not imported by either the active Streamlit app or the FastAPI backend:

- `rewrite_tab_4pi.py`: Alternate dashboard variant with Trading 212 CSV analysis and local encrypted credentials (not wired into active flow).
- `verify_client.py`: Standalone Alpaca market data client verification script.
- `debug_positions.py`: Standalone debug script for Trading 212 position calculations.
- `plot_portfolio_weights.py`: Deprecated plot script. Note: `rewrite_plot_portfolio_weights.py` remains in the root and is the active module used by `rewrite_tab_1.py`.
- `scrape_news_playwright.py`: Standalone news scraping prototype using Playwright.
- `scrape_news_requests.py`: Standalone news scraping prototype using Requests.

> **Note:** Imports within these files are intentionally preserved in their legacy state for historical reference.
