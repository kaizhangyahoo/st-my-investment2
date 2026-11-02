# st-my-investment2: Portfolio Management & Analytics

[![Jira Issue](https://img.shields.io/badge/Jira-KAN--3-blue)](https://kaizhang.atlassian.net/browse/KAN-3)
[![Confluence Spec](https://img.shields.io/badge/Confluence-Design%20Spec-0052CC)](https://kaizhang.atlassian.net/wiki/spaces/LC/pages/1409056769)

## 📌 Architecture Overview (KAN-3: De-Streamlit)
This repository hosts the **Portfolio Management Dashboard and Analytics** application. As specified in **[KAN-3](https://kaizhang.atlassian.net/browse/KAN-3)**, the monolithic Streamlit architecture has been refactored into a decoupled, modern Web Application:
- **Frontend:** React 18, Vite, TypeScript, and Tailwind CSS.
- **Backend:** Python 3.11+ FastAPI REST API with Pydantic v2 schemas and modular service engines.
- **Local Dev Workflow:** Python CLI runner (`cli.py`) inspired by the CV-creator pattern.

For complete technical specifications, see the **[Confluence Architecture & Technical Design Page](https://kaizhang.atlassian.net/wiki/spaces/LC/pages/1409056769)**.

---

## 🏛 System Architecture

```mermaid
flowchart TB
    subgraph Client["Frontend: React + Vite (TypeScript)"]
        UI["Tailwind UI / Responsive Layout"]
        Auth["Auth Gate: JWT / Email / OAuth"]
        
        subgraph Views["Views & Components"]
            Holdings["Holdings & P&L Table"]
            Upload["CSV Drag & Drop Uploader"]
            Tickers["Interactive Ticker Editor"]
            Charts["Currency & Allocation Charts"]
            T212["Trading 212 API Sync"]
        end

        UI --> Views
    end

    subgraph CLI["Developer CLI Runner (cli.py)"]
        DevCmd["python cli.py dev"]
        StartCmd["python cli.py start"]
    end

    subgraph Server["Backend: FastAPI (Python 3.11+)"]
        API["FastAPI App (/api/v1)"]
        
        subgraph Endpoints["Endpoints"]
            AuthEP["/auth"]
            TradesEP["/trades"]
            PortfolioEP["/portfolio"]
            TickersEP["/tickers"]
            MarketEP["/market-data"]
            T212EP["/trading212"]
        end

        subgraph Services["Service Engines"]
            Engine["Portfolio Calculation Engine"]
            Market["Market Data & FX Aggregator"]
            TickerSvc["SEC EDGAR & Mapping Service"]
            T212Svc["Trading 212 Client"]
        end

        subgraph Storage["Storage & Caching"]
            Config["Pydantic Settings / .env"]
            Cache[("Thread-Safe TTLCache")]
            JSONFiles[("company_name_to_ticker.json<br/>user_portfolio_values.json")]
        end

        API --> Endpoints
        Endpoints --> Services
        Services --> Storage
    end

    subgraph External["External Services"]
        YF["Yahoo Finance (FX & OHLC)"]
        EODHD["EOD Historical Data"]
        Alpaca["Alpaca / TwelveData"]
        SEC["SEC EDGAR API"]
        T212Broker["Trading 212 Broker API"]
    end

    Client <-->|"REST API (JSON / FormData)"| API
    CLI -->|"Launches"| Client
    CLI -->|"Launches"| Server
    Services <--> External
```

---

## 🚀 Quickstart & Developer Guide

### 1. Prerequisites
- Python 3.10+
- Node.js 18+ and npm

### 2. Environment Setup
Copy the example environment configuration:
```bash
cp backend/.env.example backend/.env
```
*(No secrets are committed to git)*

### 3. Running Locally (CLI Runner)
Using the unified CLI runner:
```bash
# Start development environment (FastAPI on :8000 + Vite on :5173 with auto-reload)
python cli.py dev

# Serve the production build directly from FastAPI on port 8000
python cli.py start
```

---

## 📂 Project Structure
```
├── cli.py                     # Root CLI runner (CV-creator pattern)
├── backend/                   # FastAPI application
│   ├── app/
│   │   ├── main.py            # FastAPI entry & router registration
│   │   ├── core/              # Config (Pydantic BaseSettings), security, cache
│   │   ├── api/v1/            # Auth, trades, portfolio, tickers, market-data, trading212
│   │   ├── schemas/           # Pydantic v2 validation models
│   │   └── services/          # Pure calculation engines & API wrappers
│   ├── requirements.txt       # Backend dependencies
│   └── .env.example           # Configuration template
├── frontend/                  # React Single Page Application
│   ├── src/
│   │   ├── components/        # Layout, auth, dashboard, trades, tickers, trading212
│   │   ├── hooks/             # Zustand auth store & custom hooks
│   │   ├── services/          # Axios API client
│   │   └── types/             # TypeScript interfaces
│   ├── package.json           # Frontend dependencies
│   └── vite.config.ts         # Vite build & proxy configuration
└── company_name_to_ticker.json# Broker market name to Yahoo ticker mappings
```

---

## 📖 Detailed Specifications
- **Confluence Design Document:** [st-my-investment2: Web Architecture & Technical Design (KAN-3)](https://kaizhang.atlassian.net/wiki/spaces/LC/pages/1409056769)
- **Jira Story:** [KAN-3](https://kaizhang.atlassian.net/browse/KAN-3)

