# AGENTS.md

## Project Overview

Streamlit-based Portfolio Management Dashboard deployed to Google Cloud Run (GCP). Uses Firebase for auth/login logging, Playwright for browser automation, and Terraform for infrastructure.

## Key Directories & Boundaries

| Path | Purpose |
|------|---------|
| `rewrite_login.py` | **Main app entry point** — Streamlit login/auth flow, dashboard orchestrator |
| `FNZ-perf-streamlit-report.py` | Secondary Streamlit app — FNZ Vanguard performance report viewer |
| `firebase_service.py` | Firebase Firestore login event logging, email/password auth helpers |
| `alpaca_client.py`, `market_data_api.py`, `trading212_api.py` | Broker/market data API clients |
| `trading212/` | Trading212 history processing (`merge_trading212_history.py`, `t212dec.py`, `t212enc.py`) |
| `ig/` | IG broker news download scripts (Dockerized for RPI4/ARM64) |
| `terraform/` | GCP Cloud Run infrastructure (main.tf, state) |
| `.agent/` | Agent skills and workflows (cloud-deployer, playwright_testing, firebase, redeploy, test) |
| `todo/` | WIP scripts (Google News, NewsAPI client) |

## Developer Commands

### Run the app locally
```bash
streamlit run rewrite_login.py
```
Default redirect URI: `http://localhost:8501`

### Run tests (Playwright)
```bash
# Local (against localhost:8501)
pytest .agent/skills/playwright_testing/examples

# Remote (against Cloud Run)
BASE_URL=https://streamlit-app-rj6qghjncq-uc.a.run.app pytest .agent/skills/playwright_testing/examples
```

### Redeploy to Cloud Run
```bash
# 1. If .streamlit/secrets.toml changed, sync first:
gcloud secrets versions add STREAMLIT_SECRETS --data-file=".streamlit/secrets.toml"

# 2. Build and push
TAG="v$(date +%Y%m%d-%H%M)"
IMAGE="us-central1-docker.pkg.dev/project-e29b631c-29b0-4dd7-86b/streamlit-repo/streamlit-app"
gcloud builds submit --tag "$IMAGE:$TAG" --tag "$IMAGE:latest" .

# 3. Apply Terraform
cd terraform && terraform apply -auto-approve

# 4. Clean old images (keep last 2)
python3 .agent/scripts/cleanup_registry.py
```

### Pre-commit hooks
```bash
pre-commit run --all-files
```
Runs: gitleaks, detect-secrets, check-yaml, check-json, end-of-file-fixer, trailing-whitespace.

## Environment & Secrets

- **Secrets file**: `.streamlit/secrets.toml` — gitignored, contains auth config and redirect URIs
- **Firebase**: Requires `firebase-service-account.json` or `FIREBASE_SERVICE_ACCOUNT_PATH` env var. The real key is in GCP Secret Manager as `FIREBASE_SERVICE_ACCOUNT`.
- **Cloud Run env**: Detected via `os.environ.get("K_SERVICE")` — sets `IS_REMOTE = True`.
- **MCP server**: Playwright MCP at `http://192.168.1.201:8931/sse` (config in `mcp.json`).
- **Python venv**: `.venv/` — VS Code settings auto-activate it.

## Architecture Notes

- The app uses **dual auth**: Firebase email/password + GitHub OAuth via `streamlit-oauth`.
- `rewrite_login.py` dynamically imports from `.agent/skills/users-login-record-firebase/scripts/` — this is an unconventional path dependency.
- Streamlit runs on port **8501 locally** but port **8080 in Docker/Cloud Run**.
- The `company_name_to_ticker.json` and `user_portfolio_values.json` are local data files at repo root.
- `t212.dat` is a Trading212 data file at repo root.

## Testing Quirks

- Tests use `pytest-playwright`, not a separate test framework.
- Streamlit dynamic IDs — use `data-testid` or text-based selectors, not auto-generated IDs.
- OAuth redirects make login testing hard; focus on email/password auth in automated tests.

## Important Constraints

- **No secrets in repo**: pre-commit hooks enforce this strictly (gitleaks + detect-secrets with `.secrets.baseline`).
- **Terraform state** is local (`terraform/terraform.tfstate`) — not remote backend.
- GCP project: `project-e29b631c-29b0-4dd7-86b`, region `us-central1`.
- Cloud Run uses **scale-to-zero** (`min_instance_count = 0`, `max_instance_count = 1`).
- Terraform version: **1.5.7**.
