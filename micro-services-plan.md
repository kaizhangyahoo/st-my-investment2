# Micro-services Plan

## Scope

- **In scope:** FastAPI backend (`backend/app`), React SPA (`frontend/`), `ig/`, Trading212 integration, observability, and the deployment path laptop → RPi4 → Cloud Run → GKE → EKS.
- **Out of scope (for now):**
  - The legacy Streamlit app stays as it is. It keeps sharing the JSON files until Stage 4.
  - Authentication is left out until Stage 2, because the first deployment is an internal server.

## Target services

| Service | Routes | Code origin | External deps | Owned state |
|---|---|---|---|---|
| **gateway** (nginx) | `/` (SPA), proxy `/api/v1/*` | `frontend/` multi-stage build | – | – |
| **portfolio-api** | `/trades/*`, `/portfolio/*`, `/telemetry/*` | `api/v1/trades.py`, `portfolio.py`, `telemetry.py`; services `portfolio_engine`, `history_service`, `realised_pnl`, `risk_metrics`, `benchmark_service` | data-api (HTTP) | `user_portfolio_values.json`, statements dir |
| **data-api** | `/market-data/quotes`, `/fx`, `/ohlc/{ticker}`, `/tickers/mappings` (GET/PUT), `/tickers/resolve`, internal batch `/price-history` | `market_service`, `price_service`, `ticker_service`, `stores/fx.py`, `stores/ticker_map.py`, `shared_service/ticker_resolution.py` | Yahoo, TwelveData, EODHD, SEC EDGAR | `fx_history.json`, `company_name_to_ticker.json` |
| **trading212** | `/trading212/*` | `t212_service`, `shared_service/trading212_api.py` | Trading212 API | instrument cache |
| **ig-ingest** (on-demand worker) | `/ig/session`, `/ig/statements/sync`, `/ig/news` | `ig/` | IG via Playwright | `news_output`, statements dir (sole writer) |
| **alloy / collector** (optional) | OTLP 4317/4318 | – | Grafana Cloud | – |
| **redis** (optional) | – | replaces in-process caches in `core/cache.py` | – | – |

### Coupling to break (`backend/app/services/`)

- `market_service` → `fx_store`, `price_service`
- `history_service` → `fx_store`, `market_service`, `ticker_service`
- `portfolio_engine` → `market_service`, `ticker_service`
- `realised_pnl` → `risk_metrics`, `ticker_service`

## Key decisions

- **JSON files**
  - Keep them at the repo root, shared with the legacy app, until Stage 4.
  - Bind-mount the **directory** to `/data`, not the individual files. Each write goes to a temp file that is then renamed over the original, and that fails on a file that is bind-mounted on its own.
  - Set the file paths through env vars in `core/config.py`.
  - Exactly one writer service per file.
  - The legacy app should re-read and merge `user_portfolio_values.json` just before it writes, so it can't overwrite newer data.
- **Frontend:** a single SPA with no micro-frontends. Organise the code into feature folders. It keeps calling `/api/v1` through the gateway.
- **Observability**
  - Stages 0–5 send to Grafana Cloud using the standard OTLP env vars.
  - On Docker Compose, Alloy is optional and runs as one shared container, not as a sidecar.
  - On GKE, Alloy runs as a DaemonSet (one per node).
  - Stage 6 uses AWS's own tools: ADOT, AMP, X-Ray, CloudWatch Logs and Amazon Managed Grafana.
- **Images:** build for both arm64 (RPi4) and amd64 (laptop and cloud) from Stage 1 on.

## Phases (engineering units)

### P0: Docker Compose baseline

- **Tasks:**
  - Backend Dockerfile running uvicorn on port 8000.
  - Gateway Dockerfile: `vite build`, served by nginx with the `/api` proxy and an SPA fallback to `index.html`.
  - JSON file paths configurable through env vars, with the directory mounted at `/data`.
  - A `DISABLE_AUTH` flag in `core/security.py`.
  - A `STATEMENTS_DIR` setting in `api/v1/trades.py`, replacing the `~/Downloads` autoload.
  - Healthchecks, and secrets in a `.env` file.
- **Done when:**
  - `docker compose up --build` works and every tab works.
  - The legacy app sees the same JSON files.

### P1: Store interfaces and the propagating HTTP client — DONE (absorbed, not a phase)

**Status:** done — stores + atomic writes. `core/http.py` was pulled forward from P2; its first
caller (`services/data_client.py`) and the removal of the `services/fx_store.py` shim both landed
with P2.

Done, and deliberately not kept as a milestone: its own acceptance criterion was "nothing behaves
differently", which is no outcome at all. What exists is the precondition for P2:

- `backend/app/stores/{fx,ticker_map,portfolio_values}.py` — the three stores, JSON-backed, each
  writing through `core/json_store.py` (temp file + rename, so a crash mid-write cannot truncate a
  shared file).
- `backend/app/core/http.py` — `PropagatingSession`, which passes on `X-Request-ID` and the W3C
  `traceparent` header. No callers until P2; it is what satisfies P2's cross-service log join.

**The `common` package was considered and rejected.** `backend/app/core` is already a leaf (nothing
in it imports `services/` or `api/`), so renaming it bought the name and not the property, and the
split needs no second image (see the one-image decision in P2). The standing rule that replaces it:
**a module does not move to a shared location until a second service actually imports it.**

### P2: Extract data-api (market-data + reference-data, merged) — IMPLEMENTED

**Status:** code done, suite green (532 tests, incl. `test/functionalTest/test_data_api_split.py`).
Not yet verified on Docker; the cross-service request-ID check in Grafana is still open.

- **As built:**
  - `SERVICE_ROLE` (`all` | `portfolio` | `data`) picks the routers in `main.py`. `all` is the
    monolith and the default, so the laptop and the RPi run exactly as before.
  - `DATA_API_URL` switches `services/data_client.py` from in-process to HTTP. `history_service`
    and `portfolio_engine` import prices / FX / coverage from it; `ticker_service.load_ticker_mappings`
    swaps its body when the URL is set.
  - data-api serves `/api/v1/internal/{quotes,fx,fx/coverage,price-history,ticker-mappings}`,
    mounted only under `SERVICE_ROLE=data`. No user auth: the gateway returns 404 for
    `/api/v1/internal/`, and the routes don't exist on the monolith.
  - data-api failures degrade like provider failures (unpriced + recorded failure; FX fallback
    with no coverage), except ticker mappings, which raise rather than cache an empty map.
  - Gateway: `nginx.conf.template` routes `/api/v1/(market-data|tickers)/` to
    `${DATA_API_UPSTREAM}` (default `backend:8000`).
  - `docker-compose.split.yml` overlays the split:
    `docker compose -f docker-compose.yml -f docker-compose.split.yml up -d --build`.
  - `services/fx_store.py` removed; `market_service` owns an `FxStore` and exposes
    `fx_covered_through()`.

- **Depends on:** nothing outstanding.
- **Why merged:** the two were never independent. Same shape (call a provider, cache, serve), same
  consumers, and `ticker_service` already has five internal callers that overlap almost entirely
  with market-data's three. `history_service` alone touches all three JSON files. Split in two, one
  `POST /portfolio/history/compute` fans out to both; merged, it fans out to one.
- **Tasks:**
  - `history_service` and `portfolio_engine` call data-api over `backend/app/core/http.py` instead
    of importing `market_service` / `ticker_service`.
  - **Expose `/price-history` as a batch endpoint.** `history_service._price_frame` loops tickers
    sequentially and emits one span per ticker precisely because that loop is the suspected
    bottleneck of the route. N HTTP calls would make it strictly worse; one batch call per request
    makes it better than today.
  - **Reuse the existing ticker-map cache seam.** Swap the *body* of
    `ticker_service.load_ticker_mappings` from `_store.read()` to an HTTP GET. Its
    `@ttl_cache(ttl=300, name="ticker_map")`, the TTL and the `cache.ticker_map.*` span attributes
    all survive untouched. Keep the cache on the module-level function, never on a method —
    `ttl_cache` keys on stringified args, so `self`'s address-bearing repr would miss every call.
  - **Remove the `services/fx_store.py` shim in the same change that introduces the first
    `PropagatingSession` caller.** `market_service` and the market-data route import
    `backend.app.stores.fx.FxStore` directly; tests patch the store, not the shim. Doing both in
    one change means `http.py` is exercised by a real caller the moment the FX path is rewired,
    and no second indirection survives into data-api.
- **Packaging:** one image, two uvicorn commands — not a second Dockerfile. Compose already builds
  `portfolio-backend:local`; data-api reuses it with a different uvicorn target. The HTTP boundary
  is what decouples the code; a separate image and dependency set buys nothing at this scale and
  doubles the arm64+amd64 build matrix.
- **Done when:**
  - The price fallback, OHLC, history, ticker map, mapping save and unresolved-symbol gate tests pass.
  - The same request ID appears in the logs of both services.

### P3: Extract reference-data

Merged into P2 — data-api owns both JSON files and both route groups.

### P4: Extract trading212 — IMPLEMENTED

**Status:** code done, suite green (534 tests). Not yet verified on Docker.

- **As built:**
  - `SERVICE_ROLE=trading212` mounts only the Trading212 router. Nothing else calls it, so there
    are no `/internal` routes and no HTTP client.
  - `portfolio` and `all` still mount it; P6 removes it from `portfolio`.
  - `docker-compose.split.yml` adds a `trading212` service (same image) and sets `T212_UPSTREAM`
    on the gateway.
  - Gateway: `nginx.conf.template` now routes `/api/v1/trading212/` to `${T212_UPSTREAM}` and
    `/api/v1/(market-data|tickers)/` to `${DATA_API_UPSTREAM}` (both default to `backend:8000`),
    and returns 404 for `/api/v1/internal/`. `frontend/Dockerfile` now installs it as an nginx
    template; before this it still copied the renamed `nginx.conf`, so the P2 routing was not
    in the image.
- **Depends on:** nothing outstanding.
- **Done when:** the Trading212 endpoint tests pass, and the gateway reaches the service in Docker.

### P5: ig-ingest (frontend-triggered) — PLANNED, not started

- **Depends on:** nothing; independent of the other phases.
- **What it does:** two tasks, chosen by which frontend button is clicked. Each click is one run;
  there is no schedule.
  1. **Sync statements:** log in to IG, download the latest `Trade*.csv` and `Transaction*.csv`
     into the statements volume, then delete the older `Trade*.csv` / `Transaction*.csv` there.
     The backend's existing autoload (`find_latest_download_files` in `api/v1/trades.py`,
     reading `STATEMENTS_DIR`) picks them up unchanged.
  2. **Instrument news:** log in, search IG news for one instrument, return the headlines to the
     frontend and append them to `news_output/ig.news.<instrument>.{csv,md}` (existing headline
     dedup kept).
- **Shape — an on-demand worker, not a compose job.** A `profiles: [jobs]` container cannot be
  started by a browser click without giving the backend the Docker socket (root on the host), so
  that is rejected. `ig-ingest` is a long-running FastAPI service in its own image (the Playwright
  base is ~1.5 GB, so it does not join `portfolio-backend:local`). It is idle between clicks;
  Chromium is launched per request and closed afterwards. One run at a time; a concurrent click
  gets 409.
  - `POST /api/v1/ig/session` — body `{username, password}`; logs in, sets the session cookie.
  - `POST /api/v1/ig/statements/sync` — task 1; returns the new filenames and how many were removed.
  - `POST /api/v1/ig/news` — body `{instrument, max_items}`; task 2; returns the headlines.
  - `GET /health`.
  - Gateway: `location /api/v1/ig/` → `${IG_UPSTREAM}`, `proxy_read_timeout` ≥ 180s (the login
    alone waits ~15s for the platform).
- **Credentials:** prompt on the first click of either button, reuse for the other. **The password
  is never stored in a cookie or browser storage** (readable by any XSS, sent on every request):
  - The frontend posts username + password once to `/ig/session`.
  - ig-ingest logs in, keeps only the Playwright `storage_state` (IG's own session cookies) in
    memory under a random id, and discards the password.
  - That id is returned as a cookie: `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/ig`,
    max-age ~30 min to match IG's session.
  - Later clicks send only the cookie. When IG expires the session or ig-ingest restarts, the
    endpoint returns 401 and the frontend prompts again.
  - Credentials never appear in argv, logs or span attributes (today's scripts pass `--password`
    on the command line, visible in `ps` and `docker inspect`).
- **Code changes:**
  - `ig/ig.sequentially.news.download.py` — the one script kept. Split `run()` into
    `login(page, username, password)` → storage state, `scrape_news_for_instrument` (exists), and
    a new `download_statements(page, dest_dir)`. The CLI `main()` stays for manual runs but reads
    `IG_USERNAME` / `IG_PASSWORD` from the environment, and drops the hardcoded default username.
  - `ig/service.py` (new) — the FastAPI app, calling those functions in a worker thread
    (`sync_playwright` cannot run on the event loop).
  - `ig/Dockerfile.news` — run `uvicorn ig.service:app`; remove `COPY alpaca_client.py` and
    `COPY company_name_to_ticker.json` (the sequential script imports neither; the map was only
    reachable through the optional `--input` flag).
  - Delete `ig/ig.async.5semaphore.news.download.py` (sequential kept: lower RAM on the RPi4).
  - Delete `ig/docker-compose.news.yml` (duplicates the root compose; hardcodes a username).
  - `ig/README.md` — rewrite for the service.
  - `docker-compose.yml` — replace the `ig-news` job with an `ig-ingest` service: no profile,
    `restart: unless-stopped`, `${STATEMENTS_DIR:-./statements}:/statements` read-write (still
    `:ro` on `backend`, so ig-ingest is the only writer) and
    `${NEWS_OUTPUT_DIR:-./news_output}:/news_output`. No IG credentials in `.env`.
  - `frontend/nginx.conf.template` + `frontend/Dockerfile` — the `/api/v1/ig/` route and the
    `IG_UPSTREAM` default (`ig-ingest:8000`).
  - Frontend:
    - `services/` — an `igIngest` client (`createSession`, `syncStatements`, `fetchNews`) with
      `credentials: 'include'`; a 401 means "prompt again".
    - A shared `IgLoginPrompt` modal plus a hook that opens it on 401 and retries the click once.
    - `components/dashboard/IgAnalyticsView.tsx` — a "Sync from IG" button beside the upload
      control; on success, the same refresh as `onUploadComplete`.
    - `components/trading212/T212View.tsx` — a "News" button next to the `NET UNREALISED P&L`
      label in the Single Instrument Inspector & Execution Blotter; headlines show in the
      inspector. (The IG inspector in `IgAnalyticsView.tsx` has no such label; add it there too
      if wanted.)
- **Deletion rule for old statements:** only `Trade*.csv` / `Transaction*.csv` directly in
  `/statements`, only after the new pair has been written and parsed; never recurse, never follow
  symlinks.
- **Done when:**
  - "Sync from IG" leaves exactly one new `Trade*.csv` + `Transaction*.csv` in the statements
    volume and the IG tab reloads from them.
  - "News" in the inspector shows headlines, and `news_output` gains them.
  - The second button does not prompt again within the session; after expiry it does.
  - No password in `docker inspect`, logs or traces.
  - Unit tests with Playwright stubbed: cookie flags, 401 on unknown session, 409 on a concurrent
    run, old statements deleted only after a successful download.

### P6: Slim down portfolio-api

- **Depends on:** P2–P4.
- **Tasks:**
  - Remove the code that has moved to other services.
  - Either run a single replica or persist the trades store, which is currently in memory.

### PA: Authentication

- Re-enable Firebase login.
- Keep the JWT check in `backend/app/core/security.py`; data-api gets it by running the same image.
- Add a frontend login page.
- Turn `DISABLE_AUTH` off.

## Stages → phases

### S0: Laptop + Grafana Cloud (current)

- **Phases:** none.
- **Do:** set the OTLP endpoint and headers through env vars.

### S1: Internal RPi4 server

- **Phases:** P0 + P5.
- **Do:**
  - Keep the backend as one service (no split), because the Pi has limited RAM.
  - Build arm64 images with `docker buildx`.
  - Send OTLP directly to Grafana Cloud; Alloy is optional.
  - No Redis.

### S2: Login page

- **Phases:** PA. (The store interfaces this stage used to wait for already exist.)

### S3: Cloud Run

- **Phases:** P2, P4, P6.
- **Do:**
  - Move the ticker map and portfolio values to Firestore here. A stopgap is a GCS volume with `max_instances=1`.
  - Persist the trades store to GCS or Firestore.
  - No Redis.
  - Route requests through either an nginx service, Firebase Hosting rewrites or a load-balancer URL map.

### S4: JSON → Firestore

- **Do:**
  - Add the Firestore store implementations and run a one-off migration.
  - Point the legacy Streamlit app at Firestore.
  - Move `fx_history` to Firestore or a GCS cache.
  - Remove the dependency on the JSON files.

### S5: GKE (Autopilot)

- **Do:**
  - Helm charts.
  - Gateway API / GCLB ingress.
  - ig-ingest as a Deployment (one replica; event-triggered from the frontend, not a CronJob).
  - Alloy DaemonSet sending to Grafana Cloud.
  - Workload Identity for Firestore access.
  - Secret Manager CSI driver.
  - Artifact Registry.
  - Memorystore if a shared cache is needed.

### S6: Multi-cloud resilience (EKS)

- **Topology:** GKE primary, EKS standby.
- **Deployment:**
  - The same Helm charts with per-cloud values files.
  - An ECR mirror of the images.
  - Terraform per cloud.
- **Observability:**
  - ADOT DaemonSet sending metrics to AMP, traces to X-Ray and logs to CloudWatch Logs.
  - Dashboards in Amazon Managed Grafana.
- **Identity and secrets:**
  - IRSA or EKS Pod Identity.
  - AWS Secrets Manager, synced through the External Secrets Operator.
- **Failover:** Route 53 health checks.
- **Data (decided: sync to DynamoDB):**
  - Add a DynamoDB implementation behind the `backend/app/stores/` interfaces; EKS uses DynamoDB, GKE uses Firestore.
  - Replicate Firestore → DynamoDB continuously (Firestore change triggers / Cloud Function or Eventarc → writer into DynamoDB). Survives a full GCP outage.
  - Use DynamoDB global tables for multi-region inside AWS.
  - Active/passive keeps one writer at a time, so one-way sync is enough day to day. On failover, DynamoDB becomes primary; failback needs a reverse sync (DynamoDB Streams → Firestore) before switching back.
  - Records carry `updated_at`, so the sync can resolve conflicts with last-write-wins.

### Preparing for S6 throughout

- Keep the store interfaces cloud-neutral.
- Pass the W3C `traceparent` header between services, not only `X-Cloud-Trace-Context`.
- Use only portable Kubernetes manifests.
- Pass all endpoints and credentials through env vars.

## Verification

- `docker compose up --build`, then check `/health` for each service through the gateway.
- Run `python -m unittest` inside each service image; the functional tests map onto the services.
- Check the SPA manually: dashboard, upload, history compute and the T212 tab.
- Confirm the same request ID or trace appears across services in Grafana (Amazon Managed Grafana in S6).

## Split timing

- S1–S2: gateway + one backend + ig-ingest job (P0, P5, PA).
- S3 onwards: full split (P2, P4, P6).
