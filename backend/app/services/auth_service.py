import os
import json
import requests
from typing import Optional, Dict, Any
from backend.app.core.config import settings

def _get_api_key() -> Optional[str]:
    return settings.FIREBASE_API_KEY or os.environ.get("FIREBASE_API_KEY")

def sign_in_with_email_password(email: str, password: str) -> Dict[str, Any]:
    api_key = _get_api_key()
    if not api_key:
        # Dev fallback mode if no API key is configured
        return {
            "success": True,
            "user_id": "dev-user-123",
            "email": email,
            "display_name": email.split("@")[0],
            "id_token": "mock-firebase-id-token",
            "error_message": None
        }

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    try:
        res = requests.post(url, json=payload, timeout=10)
        data = res.json()
        if res.status_code == 200:
            return {
                "success": True,
                "user_id": data.get("localId"),
                "email": data.get("email"),
                "display_name": data.get("displayName"),
                "id_token": data.get("idToken"),
                "error_message": None
            }
        return {"success": False, "error_message": data.get("error", {}).get("message", "Login failed")}
    except Exception as e:
        return {"success": False, "error_message": str(e)}

def sign_up_with_email_password(email: str, password: str) -> Dict[str, Any]:
    api_key = _get_api_key()
    if not api_key:
        return {
            "success": True,
            "user_id": "dev-user-signup",
            "email": email,
            "id_token": "mock-firebase-id-token",
            "error_message": None
        }

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    try:
        res = requests.post(url, json=payload, timeout=10)
        data = res.json()
        if res.status_code == 200:
            return {
                "success": True,
                "user_id": data.get("localId"),
                "email": data.get("email"),
                "id_token": data.get("idToken"),
                "error_message": None
            }
        return {"success": False, "error_message": data.get("error", {}).get("message", "Sign up failed")}
    except Exception as e:
        return {"success": False, "error_message": str(e)}

def log_login_event(user_email: str, provider: str = "unknown", user_name: Optional[str] = None, user_id: Optional[str] = None) -> bool:
    try:
        from firebase_service import log_login_event as fb_log
        return fb_log(user_email=user_email, user_name=user_name, provider=provider, user_id=user_id)
    except Exception:
        # Graceful fallback if firebase-admin is unconfigured locally
        return True

