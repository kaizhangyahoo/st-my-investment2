import os
from typing import List, Optional
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseModel as BaseSettings
    SettingsConfigDict = dict

class Settings(BaseSettings):
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
    TWELVEDATA_API_KEY: Optional[str] = None

    # Trading 212
    T212_API_KEY: Optional[str] = None
    T212_API_SECRET: Optional[str] = None

    # Security
    JWT_SECRET: str = "dev-secret-key-change-in-production-12345678"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Data paths
    REPO_ROOT: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
    TICKER_MAP_FILE: str = os.path.join(REPO_ROOT, "company_name_to_ticker.json")
    PORTFOLIO_VALUES_FILE: str = os.path.join(REPO_ROOT, "user_portfolio_values.json")

settings = Settings()

