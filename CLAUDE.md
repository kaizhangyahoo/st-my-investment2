# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run locally:**
```bash
streamlit run rewrite_login.py
```
The app runs on `http://localhost:8501`. Secrets must exist at `.streamlit/secrets.toml` (not committed).

**Run the standalone FNZ report page:**
```bash
streamlit run FNZ-perf-streamlit-report.py
```

**Run unit tests:**
```bash
python -m unittest verify_client
```

**Run Playwright E2E tests** (requires app running locally first):
```bash
pytest .agent/skills/playwright_testing/examples
```

**Pre-commit hooks:**
```bash
pre-commit run --all-files
```
Hooks: `gitleaks` (secret detection), `detect-secrets` (baseline: `.secrets.baseline`), check-yaml/json, large file check, trailing whitespace/EOF fixes.

**Deploy to GCP Cloud Run:**
```bash
TAG="v$(date +%Y%m%d-%H%M)"
IMAGE="us-central1-docker.pkg.dev/project-e29b631c-29b0-4dd7-86b/streamlit-repo/streamlit-app"
gcloud builds submit --tag "$IMAGE:$TAG" --tag "$IMAGE:latest" .
cd terraform && terraform apply -auto-approve
```
See `terraform/README.MD` for rollback and teardown instructions.

**Sync secrets to GCP before deploying if `.streamlit/secrets.toml` changed:**
```bash
gcloud secrets versions add STREAMLIT_SECRETS --data-file=".streamlit/secrets.toml"
```

**Clean up old container images (keep last 2):**
```bash
python3 .agent/scripts/cleanup_registry.py
```

## Architecture

### Entry Point Flow

`rewrite_login.py` is the sole Streamlit entry point (as in the Dockerfile CMD). It:
1. Checks for `?view=legal` query param and renders the legal page if present.
2. Renders the OAuth/email login page if not authenticated.
3. On successful login, runs `exec(open("rewrite_tab_1.py").read())` — the dashboard runs in the login script's namespace, not as an imported module.

Authentication supports: Google (Streamlit native OIDC), GitHub/Facebook (streamlit-oauth), and email/password (Firebase REST API). Login events are logged to Firestore via `firebase_service.py`.

### Key Source Files

| File | Purpose |
|---|---|
| `rewrite_login.py` | Auth gate and app entry point |
| `rewrite_tab_1.py` | Main portfolio dashboard (~1100 lines, procedural) |
| `rewrite_tab_4pi.py` | Alternate dashboard variant with Trading 212 CSV analysis and local encrypted credential support — not wired into the main login flow |
| `rewrite_plot_portfolio_weights.py` | Plotly charting functions (portfolio weights, cashflow waterfall, value time series, benchmark comparison, ticker price + trade markers) |
| `rewrite_ticker_resolution.py` | Resolves instrument names → Yahoo Finance tickers via SEC EDGAR |
| `trading212_api.py` | Trading 212 REST API client with cursor-based pagination (`fetch_all_paginated()`) |
| `alpaca_client.py` | Alpaca Market Data v2 API client |
| `market_data_api.py` | Yahoo Finance OHLC, Finage (threaded with semaphore), Nasdaq Data Link classes |
| `getEODprice.py` | TwelveData and EOD Historical Data price fetching |
| `firebase_service.py` | Firebase Admin SDK init, Firestore login logging (symlinked from `.agent/skills/users-login-record-firebase/scripts/`) |
| `miniEnc.py` | XOR+base64 obfuscation for API keys embedded in source — obfuscation only, not real encryption |
| `trading212/t212enc.py` / `t212dec.py` | Fernet/PBKDF2 encryption for Trading 212 API credentials stored in `trading212/t212.dat` |
| `company_name_to_ticker.json` | Editable cache mapping instrument names to Yahoo Finance tickers |
| `user_portfolio_values.json` | On-disk cache of historical portfolio values keyed by account ID |

### State Management

- **Auth state**: `st.session_state.email_user` / `github_user` / `facebook_user` set on login.
- **Data caching**: `@st.cache_data` with `ttl=3600` on expensive API calls. Historical portfolio values are additionally persisted to `user_portfolio_values.json`.
- **Widget state**: Ticker resolution UI uses per-row keys like `f"include_{market_name}"` and `f"ticker_{market_name}"`.

### Secrets / Environment

- **Local**: `.streamlit/secrets.toml` (gitignored). Contains API keys for all external services and OAuth credentials.
- **Production**: GCP Secret Manager (`FIREBASE_SERVICE_ACCOUNT`, `STREAMLIT_SECRETS`), injected by Cloud Run at runtime.
- **Environment detection**: `os.environ.get("K_SERVICE")` — set by Cloud Run, absent locally.
- **API key obfuscation**: Some keys (TwelveData, Finage, Nasdaq) are obfuscated in source via `miniEnc.py`. Do not treat this as secure.

### Data Fetching

All prices are converted to GBP using GBPUSD and GBPEUR rates from Yahoo Finance. The `Finage` class uses `threading.Thread` with `Semaphore(8)` for concurrent price fetching. Trading 212 pagination uses cursor-based `nextPageId` in `fetch_all_paginated()`.

### Infrastructure

- **GCP Project**: `project-e29b631c-29b0-4dd7-86b`, region `us-central1`
- **Live URL**: `https://streamlit-app-rj6qghjncq-uc.a.run.app`
- **Container base**: `mcr.microsoft.com/playwright/python:v1.49.0-noble` (Playwright needed for IG scraper)
- **Terraform**: manages Cloud Run service, IAM, and Secret Manager access. State file at `terraform/terraform.tfstate`.
