"""Drive the React dev UI headlessly and capture screenshots for visual verification.

Steps run in order and are given as repeated --step arguments:
  click:<text>        click the first visible element containing <text>
  click-css:<sel>     click the first element matching a CSS selector
  wait:<ms>           pause (e.g. for charts / API calls)
  wait-for:<text>     wait until <text> is visible
  shot:<name>         save a screenshot to <out-dir>/<name>.png
  drag:<sel>:<dx>     drag horizontally inside the element matching <sel> (e.g. zoom a Plotly chart)

Example:
  .venv/bin/python .agent/skills/web-ui-testing/scripts/ui_probe.py \
      --step "click:IG CSV Analysis" --step "wait:3000" \
      --step "click-css:tbody tr >> nth=0" --step "wait-for:PRICE TRAJECTORY" \
      --step "wait:4000" --step "shot:inspector"
"""
import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def run(url: str, steps: list[str], out_dir: Path, width: int, height: int, timeout: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    failed_requests: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_default_timeout(timeout)
        page.on("console", lambda m: m.type == "error" and console_errors.append(m.text))
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        page.on(
            "response",
            lambda r: r.status >= 400 and failed_requests.append(f"{r.status} {r.request.method} {r.url}"),
        )

        page.goto(url, wait_until="networkidle")
        exit_code = 0
        for step in steps:
            kind, _, arg = step.partition(":")
            print(f"-> {step}")
            try:
                if kind == "click":
                    page.get_by_text(arg, exact=False).first.click()
                elif kind == "click-css":
                    page.locator(arg).first.click()
                elif kind == "wait":
                    page.wait_for_timeout(int(arg))
                elif kind == "wait-for":
                    page.get_by_text(arg, exact=False).first.wait_for(state="visible")
                elif kind == "shot":
                    path = out_dir / f"{arg}.png"
                    page.screenshot(path=str(path))
                    print(f"   saved {path}")
                elif kind == "drag":
                    sel, _, dx = arg.rpartition(":")
                    box = page.locator(sel).first.bounding_box()
                    if not box:
                        raise RuntimeError(f"no bounding box for {sel}")
                    x, y = box["x"] + box["width"] * 0.4, box["y"] + box["height"] / 2
                    page.mouse.move(x, y)
                    page.mouse.down()
                    page.mouse.move(x + int(dx), y, steps=10)
                    page.mouse.up()
                else:
                    raise ValueError(f"unknown step kind: {kind}")
            except Exception as e:  # report and keep a screenshot of the failure state
                print(f"   FAILED: {e}")
                page.screenshot(path=str(out_dir / "failure.png"))
                exit_code = 1
                break

        browser.close()

    print(f"console errors: {len(console_errors)}")
    for e in console_errors:
        print(f"   {e}")
    print(f"failed requests: {len(failed_requests)}")
    for r in failed_requests:
        print(f"   {r}")
    return exit_code


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:5173")
    ap.add_argument("--step", action="append", default=[])
    ap.add_argument("--out-dir", default="scratch/ui-shots")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--timeout", type=int, default=15000)
    a = ap.parse_args()
    sys.exit(run(a.url, a.step, Path(a.out_dir), a.width, a.height, a.timeout))
