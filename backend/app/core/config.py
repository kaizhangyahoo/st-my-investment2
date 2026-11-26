import os
from typing import ClassVar, List, Optional, Tuple
# deliberately unguarded
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),  # backend/.env
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Which fields hold credentials, read by `redaction.collect_secret_literals` to decide what to
    # mask in a log line. Declared here so adding a provider key below is enough to get it
    # redacted, with no second edit in the redactor. A ClassVar rather than a field, so no
    # environment variable can switch redaction off.
    SECRET_FIELD_NAMES: ClassVar[Tuple[str, ...]] = (
        "JWT_SECRET",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "FIREBASE_API_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "EODHD_API_TOKEN",
        "FINAGE_API_KEY",
        "TWELVEDATA_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "POLYGON_API_KEY",
        "T212_API_KEY",
        "T212_API_SECRET",
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

    # Service split (P2). SERVICE_ROLE picks the routers one process mounts: "all" is the
    # monolith (laptop, RPi), "portfolio" and "data" are the two halves of the split. With
    # DATA_API_URL set, market data, FX and ticker mappings are fetched from data-api over HTTP
    # instead of computed in-process; unset, everything stays in-process.
    SERVICE_ROLE: str = "all"  # all | portfolio | data
    DATA_API_URL: Optional[str] = None  # e.g. http://data-api:8000
    DATA_API_TIMEOUT: float = 120.0  # a cold price-history batch can take a while

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
    # Folder scanned for the latest IG Trade*/Transaction*.csv statements when nothing is uploaded.
    STATEMENTS_DIR: str = "~/Downloads"

settings = Settings()
