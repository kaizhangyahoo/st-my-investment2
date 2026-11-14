# st-my-investment2: Portfolio Management & Analytics

[![Jira KAN-3](https://img.shields.io/badge/Jira-KAN--3%20De--Streamlit-blue)](https://kaizhang.atlassian.net/browse/KAN-3)
[![Jira KAN-6](https://img.shields.io/badge/Jira-KAN--6%20Stitch%20Redesign-emerald)](https://kaizhang.atlassian.net/browse/KAN-6)
[![Confluence Spec](https://img.shields.io/badge/Confluence-Design%20Spec-0052CC)](https://kaizhang.atlassian.net/wiki/spaces/LC/pages/1409056769)

## 📌 Architecture Overview

This repository hosts the **Portfolio Management Dashboard and Analytics** application. Originally built as a monolithic Streamlit application, it has transitioned to a modern, decoupled web architecture:
- **Frontend:** Single Page Application (SPA) built with React 18, Vite, TypeScript, and Tailwind CSS.
- **UI/UX Design:** High-fidelity, institutional dark financial terminal styled from **Google Stitch** (Project: *Kai Family Office*, ID: `12026627589197832258`).
- **Backend:** High-performance RESTful API built with Python 3.11+, FastAPI, and Pydantic v2.
- **Local Dev Workflow:** Unified Python CLI runner (`cli.py`) enabling one-command local launching of both services.
- **Decoupled Login for Prototyping:** Local development directly opens the active terminal workspaces without requiring authentication gates.

---

## 🏛 System Architecture & Workspaces

The application features four institutional workspaces accessible via the persistent sidebar:

1. **IG CSV Analysis (`/` - default view):**
   - Drag-and-drop ingestion of IG Broker statements (`Trade*.csv` and `Transaction*.csv`).
   - Consolidated portfolio telemetry (Total Market Value, Cash Buffer, Cost Basis, Unrealized P&L).
   - Real-time holdings ledger with 7-day trend sparklines, exchange taxonomy, and P&L color coding.
   - Currency & sector allocation donut chart (USD, GBP, EUR exposure).
   - Single Instrument Inspector with interactive ticker switcher, execution markers (Buys/Sells), and trade fill history.
   - Recent quarters trade activity blotter with `ALL`, `BUYS`, and `SELLS` quick filters.
   - Cashflow waterfall breakdown (dividends, cash interest, broker commissions, stamp duty).

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
            TradesEP["/trades (upload, summary, waterfall)"]
            T212EP["/trading212 (overview, positions)"]
            TickersEP["/tickers (mappings, resolve)"]
            PortfolioEP["/portfolio (history, benchmark)"]
            MarketEP["/market-data (quotes, fx, ohlc)"]
            AuthEP["/auth (login, signup, me)"]
        end

        subgraph Services["Engines & Clients"]
            Engine["Portfolio Engine (FX & Basis)"]
            T212Svc["Trading 212 Client"]
            TickerSvc["Ticker & SEC Service"]
            MarketSvc["Market Data & FX Aggregator"]
        end

        subgraph Storage["Data Store"]
            JSONMap[("company_name_to_ticker.json")]
            JSONValues[("user_portfolio_values.json")]
            MemStore[("In-Memory Statement Store")]
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
- Python 3.10+
- Node.js 18+ and npm

### 2. Environment Setup
```bash
# Backend environment variables
cp backend/.env.example backend/.env

# Local secrets & Stitch MCP API Key (gitignored)
cp .env.example .env
```

### 3. Running Locally

```bash
# Option A: Start development mode (FastAPI on :8000 + Vite on :5173 with auto-reload)
python cli.py dev

# Option B: Serve the production build directly from FastAPI on port 8000
python cli.py start
```

### 4. Building Frontend Assets
```bash
cd frontend
npm install
npm run build
```

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
