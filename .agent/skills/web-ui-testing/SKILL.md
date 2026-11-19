---
name: web-ui-testing
description: Visually verify the React + FastAPI dev UI (python cli.py dev, http://localhost:5173) with headless Playwright. Use after frontend changes to click through flows, capture screenshots, view them, and report console errors / failed API calls.
---

# Web UI Testing (React dev app)

Headless Playwright probe for the React frontend. No MCP server needed — uses the
`playwright` package and Chromium already installed in `.venv`.

## Preconditions

- Dev stack running: `python cli.py dev` (Vite on :5173, FastAPI on :8000, `/api` proxied).
- Local dev bypasses login (`useAuth` defaults to an authenticated user; backend treats a
  missing/dev token as `dev@local.host`), so no credentials are needed.
- Check it is up: `curl -s -o /dev/null -w "%{http_code}" localhost:5173` → `200`.
- If Chromium is missing: `.venv/bin/python -m playwright install chromium`.

## Usage

```bash
.venv/bin/python .agent/skills/web-ui-testing/scripts/ui_probe.py \
  --step "click:IG CSV Analysis" --step "wait:4000" \
  --step "click-css:tbody tr >> nth=0" --step "wait-for:PRICE TRAJECTORY" \
  --step "wait:5000" --step "shot:inspector"
```

Then open `scratch/ui-shots/inspector.png` with the image viewer tool and inspect it.

### Step types (run in order)

| Step | Meaning |
|---|---|
| `click:<text>` | Click first element containing text |
| `click-css:<selector>` | Click first match of a Playwright/CSS selector |
| `wait:<ms>` | Pause (charts and API calls need 3–5 s) |
| `wait-for:<text>` | Wait until text is visible |
| `shot:<name>` | Save `<out-dir>/<name>.png` |
| `drag:<selector>:<dx>` | Horizontal mouse drag (Plotly zoom: `[role=dialog] .nsewdrag:200`) |

Options: `--url`, `--out-dir` (default `scratch/ui-shots`), `--width`, `--height`, `--timeout`.

On a failed step it saves `failure.png` and exits 1. It always prints browser console
errors and HTTP ≥400 responses — treat those as findings.

## Recipes

- **Instrument inspector + chart zoom/reset**:
  `click:IG CSV Analysis` → `click-css:tbody tr >> nth=0` → `wait:5000` → `shot:a` →
  `drag:[role=dialog] .nsewdrag:200` → `shot:zoomed` → `click:RESET VIEW` → `shot:reset`
- **Specific holding**: `click-css:tbody tr:has-text('AAPL')`

## Notes

- Use visible text or roles as selectors; Tailwind class names are not stable.
- Plotly plots render in SVG; the zoomable area is `.nsewdrag`.
- For the legacy Streamlit app (:8501) use the `playwright_testing` skill instead.
