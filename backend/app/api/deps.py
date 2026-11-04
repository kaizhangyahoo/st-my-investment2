from backend.app.core.config import settings, Settings
from backend.app.core.security import get_current_user

def get_settings() -> Settings:
    return settings

