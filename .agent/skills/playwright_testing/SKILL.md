# Playwright Testing Skill

This skill provides a structured approach to testing the Streamlit Portfolio Dashboard using Playwright.

## Setup

1. Install Playwright and its dependencies:
   ```bash
   pip install playwright pytest-playwright
   playwright install
   ```

2. (Optional) Install Watchdog for better performance:
   ```bash
   pip install watchdog
   ```

## Key Components

- `scripts/auth_helper.py`: Utilities for logging in via different providers.
- `examples/test_login.py`: Basic login verification tests.
- `examples/test_dashboard.py`: Tests for dashboard features like file upload and chart rendering.

## Testing Strategy

### Authentication
Testing authentication is tricky because of OAuth redirects. We focus on:
- Email/Password auth (easiest to automate).
- Verifying the presence and link targets of OAuth buttons.

### UI Validation
- Streamlit uses dynamic IDs. Use `data-testid` or text-based selectors.
- Wait for elements to appear using `page.wait_for_selector()`.
- For Plotly charts, check for the canvas or the `svg` container.

## Usage

### Local Testing (default)
```bash
pytest .agent/skills/playwright_testing/examples
```

### Remote Testing (Cloud Run)
```bash
BASE_URL=https://streamlit-app-rj6qghjncq-uc.a.run.app pytest .agent/skills/playwright_testing/examples
```

### With Visible Browser (for debugging)
```bash
pytest .agent/skills/playwright_testing/examples/test_login.py --headed
```
