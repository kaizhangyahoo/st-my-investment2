import os
from typing import List, Optional
# deliberately unguarded
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),  # backend/.env
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "Portfolio Analytics API"
    ENVIRONMENT: str = "development"
    API_V1_STR: str = "/api/v1"
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ]

    # Firebase
    FIREBASE_SERVICE_ACCOUNT_JSON: Optional[str] = None
    FIREBASE_SERVICE_ACCOUNT_PATH: Optional[str] = None
    FIREBASE_API_KEY: Optional[str] = None

    # Market Data Providers
    ALPACA_API_KEY: Optional[str] = None
    ALPACA_SECRET_KEY: Optional[str] = None
    EODHD_API_TOKEN: Optional[str] = None
    FINAGE_API_KEY: Optional[str] = None
    TWELVEDATA_API_KEY: Optional[str] = None  # comma-separated for key rotation
    ALPHA_VANTAGE_API_KEY: Optional[str] = None
    POLYGON_API_KEY: Optional[str] = None

    # Trading 212
    T212_API_KEY: Optional[str] = None
    T212_API_SECRET: Optional[str] = None

    # Logging. LOG_FORMAT "auto" picks json under Cloud Run (K_SERVICE) and text locally.
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "auto"  # auto | json | text
    # Only used to build the Cloud Logging trace field; the field is omitted when unset.
    GCP_PROJECT_ID: Optional[str] = None

    # OpenTelemetry log export. Unset endpoint = stdout only. Service names are component-first
    # (fastapi-portfolio, web-portfolio). Read from backend/.env like everything else here.
    OTEL_SERVICE_NAME: str = "fastapi-portfolio" # override by .env
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None
    OTEL_EXPORTER_OTLP_PROTOCOL: str = "http/protobuf" 
    OTEL_EXPORTER_OTLP_HEADERS: Optional[str] = None  # e.g. Authorization=Basic <base64>
    OTEL_RESOURCE_ATTRIBUTES: Optional[str] = None

    # Security
    JWT_SECRET: str = "dev-secret-key-change-in-production-12345678"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Data paths
    REPO_ROOT: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    TICKER_MAP_FILE: str = os.path.join(REPO_ROOT, "company_name_to_ticker.json")
    PORTFOLIO_VALUES_FILE: str = os.path.join(REPO_ROOT, "user_portfolio_values.json")
    # Unlike the two above, this one is pure cache: it is rebuilt from the provider on demand and
    # is not shared with the legacy app, so it is gitignored rather than tracked.
    FX_HISTORY_FILE: str = os.path.join(REPO_ROOT, "fx_history.json")

settings = Settings()

