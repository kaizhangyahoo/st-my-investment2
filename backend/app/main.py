import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.app.core.config import settings
from backend.app.api.v1 import auth, portfolio, trades, tickers, market_data, trading212

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(portfolio.router, prefix=settings.API_V1_STR)
app.include_router(trades.router, prefix=settings.API_V1_STR)
app.include_router(tickers.router, prefix=settings.API_V1_STR)
app.include_router(market_data.router, prefix=settings.API_V1_STR)
app.include_router(trading212.router, prefix=settings.API_V1_STR)

@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.PROJECT_NAME}

# Mount static files in production if frontend build exists
frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../frontend/dist"))
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")

