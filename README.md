# st-my-investment2: Portfolio Management & Analytics

[![Jira KAN-3](https://img.shields.io/badge/Jira-KAN--3%20De--Streamlit-blue)](https://kaizhang.atlassian.net/browse/KAN-3)
[![Jira KAN-6](https://img.shields.io/badge/Jira-KAN--6%20Stitch%20Redesign-emerald)](https://kaizhang.atlassian.net/browse/KAN-6)
[![Confluence Spec](https://img.shields.io/badge/Confluence-Design%20Spec-0052CC)](https://kaizhang.atlassian.net/wiki/spaces/LC/pages/1409056769)

## 📌 Architecture Overview

This repository hosts the **Portfolio Management Dashboard and Analytics** application. Originally built as a monolithic Streamlit application, it has transitioned to a modern, decoupled web architecture:
- **Frontend:** Single Page Application (SPA) built with React 18, Vite, TypeScript, and Tailwind CSS.
- **UI/UX Design (KAN-6):** High-fidelity, institutional dark financial terminal styled and redesigned using **Google Stitch** (Project: *Kai Family Office*, ID: `12026627589197832258`). Provides a streamlined, direct-to-workspace layout without blocking login hurdles for prototyping.
- **Backend:** High-performance RESTful API built with Python 3.11+, FastAPI, and Pydantic v2.
- **Smart Statement Ingestion & Local Autoload:** Automatically inspects the local environment (`~/Downloads/Tr*.csv`) for the latest real IG statements before falling back to sample data.
- **Local Dev Workflow:** Unified Python CLI runner (`cli.py`) enabling one-command local launching of both services.
- **Decoupled Login for Prototyping:** Local development directly opens the active terminal workspaces without requiring authentication gates.

---

## 🏛 System Architecture & Workspaces

The application features four institutional workspaces accessible via the persistent sidebar:

1. **IG CSV Analysis (`/` - default view):**
   - **Local File Auto-Discovery:** Scans `~/Downloads` for `Tr*.csv` statements (`TradeHistory-*.csv` and `TransactionHistory-*.csv`), parses filename date ranges or modification timestamps, and auto-loads the latest statement. Safely falls back to the institutional sample ledger only if no local statements exist.
   - Drag-and-drop ingestion deck for manual uploading of IG Broker statements (`Trade*.csv` and `Transaction*.csv`).
   - Consolidated portfolio telemetry (Total Market Value, Cash Buffer, Cost Basis, Unrealized P&L).
   - Real-time holdings ledger with 7-day trend sparklines, exchange taxonomy, and P&L color coding.
   - Currency & sector allocation donut chart (USD, GBP, EUR exposure).
   - Single Instrument Inspector with interactive ticker switcher, execution markers (Buys/Sells), and trade fill history.
   - Recent quarters trade activity blotter with `ALL`, `BUYS`, and `SELLS` quick filters populated from parsed statements.
   - Cashflow waterfall breakdown (dividends, cash interest, broker commissions, stamp duty).
   - One-click panel reset (`POST /api/v1/trades/reset`) to purge in-memory cache and re-scan for fresh local statement files.

2. **Trading 212 API Workspace:**
   - Pure REST API integration using direct header authentication (`x-t212-key`, `x-t212-secret`).
   - 7 Bloomberg-dense telemetry cards (Value, Cash, Investments, Cost, Realised P&L, FX Impact, Unrealised P&L).
   - Live open positions blotter with spread, average buy price, and % portfolio weight.
   - Currency exposure donut and FX risk alert callout.
   - Order history and execution blotter with filled status.
   - Dividends blotter & income telemetry with yield-on-cost and projected run-rate.

3. **Reference Data & Ticker Mapping Editor:**
   - Active symbology master table (`CSV Raw String / Broker Feed` ➔ `Yahoo Ticker`).
   - Direct persistence to `company_name_to_ticker.json` on disk via FastAPI PUT endpoint.
   - Ingestion reconciliation engine with SEC EDGAR auto-resolver for unmapped symbols.
   - Live syntax-highlighted JSON store inspector.

4. **Performance Blotter:**
   - Consolidated portfolio equity curve over time from historical ledger accounts.
   - S&P 500 benchmark overlay.
   - Risk & return telemetry (Sharpe ratio, max drawdown, annualized volatility, win rate).

```mermaid
flowchart TB
    subgraph Client["Frontend: React 18 + Vite (Tailwind CSS - Stitch Dark Theme)"]
        Sidebar["Institutional Sidebar (4 Workspaces)"]
        Header["Terminal Top Header & Spot Rate Ticker"]
        
        subgraph Workspaces["Analytics Workspaces"]
            IGView["IG CSV Analysis View"]
            T212View["Trading 212 API View"]
            RefData["Reference Data & Ticker Mapping"]
            PerfView["Performance Blotter View"]
        end

        Sidebar --> Workspaces
        Header --> Workspaces
    end

    subgraph CLI["CLI Runner (cli.py)"]
        DevCmd["python cli.py dev"]
        StartCmd["python cli.py start"]
    end

    subgraph Server["Backend: FastAPI (Python 3.11+)"]
        API["FastAPI App (/api/v1)"]
        
        subgraph Endpoints["API Routers"]
            TradesEP["/trades (upload, summary, waterfall, reset)"]
            T212EP["/trading212 (overview, positions)"]
            TickersEP["/tickers (mappings, resolve)"]
            PortfolioEP["/portfolio (history, benchmark)"]
            MarketEP["/market-data (quotes, fx, ohlc)"]
            AuthEP["/auth (login, signup, me, log-event)"]
        end

        subgraph Services["Engines & Clients"]
            Engine["Portfolio Engine (FX & Basis)"]
            T212Svc["Trading 212 Client"]
            TickerSvc["Ticker & SEC Service"]
            MarketSvc["Market Data & FX Aggregator"]
        end

        subgraph Storage["Data Store & Ingestion"]
            JSONMap[("company_name_to_ticker.json")]
            JSONValues[("user_portfolio_values.json")]
            MemStore[("In-Memory Statement Store")]
            LocalDownloads[("Local ~/Downloads (Tr*.csv)")]
        end

        API --> Endpoints
        Endpoints --> Services
        Services --> Storage
    end

    Client <-->|"REST API"| API
    CLI --> Client
    CLI --> Server
```

---

## 🚀 Quickstart & Developer Guide

### 1. Prerequisites
- Python 3.11+ (3.12 recommended — dependencies are unpinned, and `pandas>=2.0.0` resolves to pandas 3.x on newer interpreters)
- Node.js 18+ and npm

### 2. Python environment
`.venv/` at the repo root is the environment that `pyproject.toml` (pyrefly) and `.vscode/settings.json` expect:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 3. Environment variables
```bash
# Backend settings, Firebase, broker/market-data keys, JWT secret
cp backend/.env.example backend/.env

# Optional, only for the Google Stitch MCP integration (gitignored, no template committed)
echo 'STITCH_API_KEY=your-key-here' > .env
```

### 4. Installing dependencies
```bash
pip install -r backend/requirements.txt   # FastAPI, Pydantic, pandas
pip install -r requirements.txt           # legacy root modules the backend still imports
npm install --prefix frontend
```
> **Both requirements files are required.** The backend reaches legacy root modules at runtime —
> `firebase_service.py` requires `firebase-admin`, `trading212_api.py` is needed for Trading 212
> integration, and `rewrite_ticker_resolution.py` is needed for SEC ticker mapping, none of which
> are included in `backend/requirements.txt`. Note that market price fetching is decoupled and
> handled independently by `backend/app/services/price_service.py` (which has no Streamlit dependency).

> **Behind a corporate package mirror,** `npm install` and `pip install` may fail even though the
> packages resolve: `frontend/package-lock.json` pins `registry.npmjs.org` URLs that an
> Artifactory-backed `.npmrc` cannot fetch (so `npm ci` is unusable), and pip can 403 on
> individual versions that the mirror has not cached — pin to a nearby version when that happens.

### 5. Running locally
```bash
# Option A: Development mode — FastAPI on :8000 and Vite on :5173, both with auto-reload
python cli.py dev

# Option B: Production build served directly from FastAPI on :8000 (runs npm run build first)
python cli.py start
```
Both options launch the frontend for you; there is no need to run `npm run dev` separately. To
build the bundle on its own, use `npm run build --prefix frontend` (outputs to `frontend/dist`).


---

## 🎨 Google Stitch Redesign (KAN-6)

As part of **[KAN-6](https://kaizhang.atlassian.net/browse/KAN-6)**, the UI was rebuilt into a dark-mode institutional trading terminal using Google Stitch:
- **Direct Workspace Navigation:** Bypasses login gates for rapid local prototyping while keeping JWT and Firebase auth endpoints available.
- **Dynamic Telemetry & Live Data Binding:** Replaced static placeholders with reactive summaries calculated from ingested broker statements.
- **Local Download Auto-Detection:** Seamless transition from mock preview to user's real portfolio by checking `~/Downloads/Tr*.csv` on startup.

---

## 🔌 Google Stitch MCP Integration

Google Stitch MCP provides AI-native design system and screen management tools directly through Model Context Protocol.

- **Endpoint:** `https://stitch.googleapis.com/mcp`
- **Transport:** HTTP JSON-RPC
- **Project Name:** Kai Family Office (`projects/12026627589197832258`)
- **Key Screens:**
  - `KAI Family Office Investment Dashboard` (`fdea23702f7f4d8b81ec716feea03a80`)
  - `Trading 212 API Portfolio Analysis` (`06a65981fac64ce9acc6f5276b495df1`)
  - `Reference Data & Ticker Mapping Editor` (`c2abfb97bc114db0a9ac72cdececda1e`)

---


## 📖 Specifications & Tracking
- **Jira Story (Frontend Redesign):** [KAN-6: Frontend redesign without login page](https://kaizhang.atlassian.net/browse/KAN-6)
- **Jira Story (Architecture):** [KAN-3: propose new design and architecture](https://kaizhang.atlassian.net/browse/KAN-3)
- **Confluence Architecture Page:** [st-my-investment2: Web Architecture & Technical Design (KAN-3)](https://kaizhang.atlassian.net/wiki/spaces/LC/pages/1409056769)
