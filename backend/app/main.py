import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.app.core.config import settings
from backend.app.core.errors import install_exception_handlers
from backend.app.core.logging_config import configure_logging
from backend.app.core.middleware import RequestContextMiddleware
from backend.app.core.otel_traces import instrument_app
from backend.app.api.v1 import auth, portfolio, trades, tickers, market_data, telemetry, trading212

# Before the app exists, so module-level logging in the routers below is already formatted.
configure_logging()

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
    # Without this the browser cannot read the correlation id on a cross-origin response.
    expose_headers=["X-Request-ID"],
)

# add_middleware inserts at position 0, so the last call is the outermost layer. This has to
# wrap CORS for the request id to be bound before anything else can log.
app.add_middleware(RequestContextMiddleware)

install_exception_handlers(app)

# No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set. The request span wraps the whole middleware
# stack whatever the call order here: the instrumentation patches build_middleware_stack rather
# than calling add_middleware. So the access line and every app log land inside the span.
instrument_app(app, settings)

# API Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(portfolio.router, prefix=settings.API_V1_STR)
app.include_router(trades.router, prefix=settings.API_V1_STR)
app.include_router(tickers.router, prefix=settings.API_V1_STR)
app.include_router(market_data.router, prefix=settings.API_V1_STR)
app.include_router(trading212.router, prefix=settings.API_V1_STR)
app.include_router(telemetry.router, prefix=settings.API_V1_STR)

@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.PROJECT_NAME}

# Mount static files in production if frontend build exists
frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend/dist"))
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")

