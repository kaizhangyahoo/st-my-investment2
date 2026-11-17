"""End-to-end check that rewrite_tab_1.py renders the real QX2B3 history without crashing.

Drives the dashboard with the actual Trade + Transaction CSVs and reports any Streamlit
exception, plus the headline figures and the period-button results (which exercise
calculate_portfolio_value_on_date, normalised in commit 5d659aa).

Usage: .venv/bin/python e2e_verify_kan_21_22_23.py [port]
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
PORT = sys.argv[1] if len(sys.argv) > 1 else "8599"
TRADE_CSV = ROOT / "TradeHistory-QX2B3-(01-11-2018)-(10-11-2026).csv"
TXN_CSV = ROOT / "TransactionHistory-QX2B3-(01-11-2018)-(10-11-2026).csv"
SHOTS = ROOT / "e2e_shots"


def settle(page, timeout=600_000):
    """Wait for Streamlit's 'Running' indicator to clear."""
    page.wait_for_timeout(2_000)
    try:
        page.wait_for_selector('[data-testid="stStatusWidget"]',
                               state="detached", timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(2_000)


def exceptions(page):
    return [e.inner_text() for e in page.query_selector_all('[data-testid="stException"]')]


def alerts(page):
    out = []
    for a in page.query_selector_all('[data-testid="stAlert"]'):
        text = a.inner_text().strip().replace("\n", " ")
        if text:
            out.append(text[:300])
    return out


def main():
    SHOTS.mkdir(exist_ok=True)
    failures = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        console_errors = []
        page.on("console", lambda m: m.type == "error" and console_errors.append(m.text[:200]))

        print(f"→ opening http://localhost:{PORT}")
        page.goto(f"http://localhost:{PORT}", wait_until="domcontentloaded", timeout=120_000)
        settle(page, timeout=120_000)

        print(f"→ uploading {TRADE_CSV.name} + {TXN_CSV.name}")
        page.set_input_files('input[type="file"]', [str(TRADE_CSV), str(TXN_CSV)])
        settle(page)

        page.screenshot(path=str(SHOTS / "01_loaded.png"), full_page=True)

        errs = exceptions(page)
        if errs:
            failures.append(f"Streamlit exception(s) after upload:\n" + "\n---\n".join(errs))
            print("✗ EXCEPTION(S) RENDERED:")
            for e in errs:
                print(e[:1500])
        else:
            print("✓ no Streamlit exception after upload")

        body = page.inner_text("body")

        # Headline figures proving prices resolved and totals computed.
        for label in ["Total market value", "Total Cash Invested", "Portfolio Value Over Time"]:
            print(f"  {'✓' if label.lower() in body.lower() else '✗'} section: {label}")

        print("\n→ alerts on page:")
        for a in alerts(page):
            print(f"  • {a}")

        # Pull the headline metric + a few table rows for the record.
        for sel, name in [('[data-testid="stMetric"]', "metrics")]:
            for el in page.query_selector_all(sel):
                print(f"  [{name}] {el.inner_text().strip().replace(chr(10), ' | ')}")

        # Period buttons exercise calculate_portfolio_value_on_date.
        print("\n→ clicking period buttons")
        for label in ["1y", "6m", "3m", "1m", "1w", "1d"]:
            btn = page.query_selector(f'button:has-text("{label}")')
            if not btn:
                failures.append(f"period button {label} not found")
                print(f"  ✗ {label}: button not found")
                continue
            btn.click()
            settle(page, timeout=300_000)

            errs = exceptions(page)
            if errs:
                failures.append(f"exception after clicking {label}: {errs[0][:400]}")
                print(f"  ✗ {label}: EXCEPTION -> {errs[0][:300]}")
                page.screenshot(path=str(SHOTS / f"err_{label}.png"), full_page=True)
                continue

            txt = page.inner_text("body")
            line = next((l for l in txt.splitlines()
                         if "Total value in GBP on" in l or "Could not calculate" in l), None)
            print(f"  {'✓' if line else '?'} {label}: {line or 'no value line found'}")
            if line and "Could not calculate" in line:
                failures.append(f"{label}: {line}")

        page.screenshot(path=str(SHOTS / "02_after_periods.png"), full_page=True)

        if console_errors:
            print(f"\n→ {len(console_errors)} browser console error(s) (first 3):")
            for c in console_errors[:3]:
                print(f"  • {c}")

        browser.close()

    print("\n" + "=" * 60)
    if failures:
        print(f"RESULT: {len(failures)} problem(s)")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("RESULT: PASS — dashboard rendered real history with no exceptions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
