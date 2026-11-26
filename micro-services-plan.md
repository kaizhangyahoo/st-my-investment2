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
| **ig-ingest** (job) | none | `ig/` | IG via Playwright | `news_output`, statements |
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

### P4: Extract trading212

- **Depends on:** nothing outstanding (the HTTP client it needs already exists).
- **Done when:** the Trading212 endpoint tests pass.

### P5: ig-ingest job

- **Depends on:** nothing; independent of the other phases.
- **Tasks:**
  - Fold `ig/` into the root compose file under `profiles: [jobs]`.
  - The job writes to the statements volume.

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
  - ig-ingest as a CronJob.
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
