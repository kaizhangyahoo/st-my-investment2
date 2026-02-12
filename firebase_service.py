"""
Firebase Service Module for Login History Logging

This module handles Firebase Firestore operations for storing user login events.
To use this module, you need:
1. A Firebase project with Firestore enabled
2. A service account key JSON file (download from Firebase Console > Project Settings > Service Accounts)
3. Set the FIREBASE_SERVICE_ACCOUNT_PATH environment variable or place the file as 'firebase-service-account.json'
"""

import os
from datetime import datetime, timezone
from typing import Optional
import json
from firebase_admin import credentials, firestore
import requests


# Firebase Admin SDK - will be initialized lazily
_firebase_app = None
_firestore_client = None


def _initialize_firebase():
    """Initialize Firebase Admin SDK if not already initialized."""
    global _firebase_app, _firestore_client
    
    if _firebase_app is not None:
        return True
    


        
    # Check if already initialized
    try:
        _firebase_app = firebase_admin.get_app()
        _firestore_client = firestore.client()
        return True
    except ValueError:
        pass
        
        # Priority 1: Environment variable containing the JSON content itself (standard Secret Manager pattern)
        # Priority 2: Environment variable containing the path to a service account file
        # Priority 3: Local default filename
        
        # Check both the combined name and the old name for backward compatibility
        service_account_data = os.environ.get('FIREBASE_CONFIG') or os.environ.get('FIREBASE_SERVICE_ACCOUNT')
        
        config_files = [
            'firebase_config.json',
            'firebase-service-account.json'
        ]
        
        if service_account_data:
            # Check if the string is actually JSON (starts with {)
            if service_account_data.strip().startswith('{'):
                try:
                    cred_info = json.loads(service_account_data)
                    # Fix for common PEM formatting issues in env vars/JSON
                    if 'private_key' in cred_info:
                        cred_info['private_key'] = cred_info['private_key'].replace('\\n', '\n')
                    cred = credentials.Certificate(cred_info)
                    _firebase_app = firebase_admin.initialize_app(cred)
                    _firestore_client = firestore.client()
                    print("✅ Firebase initialized from environment variable JSON string.")
                    return True
                except Exception as e:
                    print(f"⚠️ Failed to parse Firebase credentials JSON from environment variable: {e}")
            
            # Otherwise treat as path
            if os.path.exists(service_account_data):
                try:
                    # Use the path directly - this is more robust than manual loading
                    cred = credentials.Certificate(service_account_data)
                    _firebase_app = firebase_admin.initialize_app(cred)
                    _firestore_client = firestore.client()
                    print(f"✅ Firebase initialized from file: {service_account_data}")
                    return True
                except Exception as e:
                    # Fallback: maybe it needs the PEM fix? (rare for files)
                    try:
                        with open(service_account_data, 'r') as f:
                            cred_info = json.load(f)
                        if 'private_key' in cred_info:
                             cred_info['private_key'] = cred_info['private_key'].replace('\\n', '\n')
                        cred = credentials.Certificate(cred_info)
                        _firebase_app = firebase_admin.initialize_app(cred)
                        _firestore_client = firestore.client()
                        print(f"✅ Firebase initialized from file (with dynamic fix): {service_account_data}")
                        return True
                    except Exception as e2:
                        print(f"⚠️ Failed to initialize from file {service_account_data}: {e2}")
        
        # Try local default files
        for config_file in config_files:
            if os.path.exists(config_file):
                try:
                    # Use the path directly
                    cred = credentials.Certificate(config_file)
                    _firebase_app = firebase_admin.initialize_app(cred)
                    _firestore_client = firestore.client()
                    print(f"✅ Firebase initialized from local file: {config_file}")
                    return True
                except Exception as e:
                    # Fallback with PEM fix for merged files
                    try:
                        with open(config_file, 'r') as f:
                            cred_info = json.load(f)
                        if 'private_key' in cred_info:
                             cred_info['private_key'] = cred_info['private_key'].replace('\\n', '\n')
                        cred = credentials.Certificate(cred_info)
                        _firebase_app = firebase_admin.initialize_app(cred)
                        _firestore_client = firestore.client()
                        print(f"✅ Firebase initialized from local file (with dynamic fix): {config_file}")
                        return True
                    except Exception as e2:
                        print(f"⚠️ Failed to initialize from local file {config_file}: {e2}")
                
        print("Login history will not be recorded until Firebase is configured correctly.")
        return False
            
    except ImportError:
        print("⚠️ firebase-admin package not installed. Run: pip install firebase-admin")
        return False
    except Exception as e:
        print(f"⚠️ Failed to initialize Firebase: {e}")
        return False


def log_login_event(
    user_email: str,
    user_name: Optional[str] = None,
    provider: str = "unknown",
    user_id: Optional[str] = None,
    additional_info: Optional[dict] = None
) -> bool:
    """
    Log a user login event to Firestore.
    
    Args:
        user_email: The user's email address
        user_name: The user's display name (optional)
        provider: The authentication provider (e.g., 'google', 'github')
        user_id: Unique user identifier from the auth provider (optional)
        additional_info: Any additional metadata to store (optional)
    
    Returns:
        True if successfully logged, False otherwise
    """
    if not _initialize_firebase():
        return False
    
    try:
        login_record = {
            "email": user_email,
            "name": user_name,
            "provider": provider,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc),
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        }
        
        if additional_info:
            login_record["metadata"] = additional_info
        
        # Add to 'login_history' collection
        _firestore_client.collection("login_history").add(login_record)
        print(f"✅ Login event logged for {user_email}")
        return True
        
    except Exception as e:
        print(f"⚠️ Failed to log login event: {e}")
        return False


def get_user_login_history(user_email: str, limit: int = 50) -> list:
    """
    Get login history for a specific user.
    
    Args:
        user_email: The user's email address
        limit: Maximum number of records to return
    
    Returns:
        List of login records, ordered by timestamp descending
    """
    if not _initialize_firebase():
        return []
    
    try:
        docs = (
            _firestore_client
            .collection("login_history")
            .where("email", "==", user_email)
            .order_by("timestamp", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
        
    except Exception as e:
        print(f"⚠️ Failed to get login history: {e}")
        return []


def get_all_login_history(limit: int = 100, sort_by: str = "timestamp", sort_direction: str = "DESCENDING") -> list:
    """
    Get all login history (admin function).
    
    Args:
        limit: Maximum number of records to return
        sort_by: Field to sort by (default 'timestamp')
        sort_direction: 'ASCENDING' or 'DESCENDING' (default 'DESCENDING')
    
    Returns:
        List of all login records, ordered by timestamp descending
    """
    if not _initialize_firebase():
        return []
    
    try:
        docs = (
            _firestore_client
            .collection("login_history")
            .order_by(sort_by, direction=sort_direction)
            .limit(limit)
            .stream()
        )
        
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
        
    except Exception as e:
        print(f"⚠️ Failed to get all login history: {e}")
        return []


# ============================================================================
# Firebase Email/Password Authentication (REST API)
# ============================================================================

def _get_firebase_api_key() -> Optional[str]:
    """Get Firebase Web API Key from environment or config file."""
    # Priority 1: Environment variable FIREBASE_CONFIG or FIREBASE_SERVICE_ACCOUNT (JSON string)
    firebase_config = os.environ.get('FIREBASE_CONFIG') or os.environ.get('FIREBASE_SERVICE_ACCOUNT')
    if firebase_config and firebase_config.strip().startswith('{'):
        try:
            data = json.loads(firebase_config)
            if 'web_api_key' in data:
                return data['web_api_key']
        except Exception:
            pass

    # Priority 2: Direct environment variable
    api_key = os.environ.get('FIREBASE_API_KEY')
    if api_key:
        return api_key
    
    # Priority 3: Unified local config file
    config_files = ['firebase_config.json', 'no_git_push.xml', 'no_git_push.json']
    for config_file in config_files:
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    content = f.read()
                    
                    # If it's the new unified JSON
                    if config_file.endswith('.json'):
                        try:
                            data = json.loads(content)
                            if 'web_api_key' in data:
                                return data['web_api_key']
                            # Fallback to regex if web_api_key missing but exists in content
                        except Exception:
                            pass
                            
                    # Regex fallback for XML or malformed JSON
                    import re
                    match = re.search(r'apiKey["\s:]+["\']?([A-Za-z0-9_-]+)', content)
                    if not match: # Try web_api_key specifically
                        match = re.search(r'web_api_key["\s:]+["\']?([A-Za-z0-9_-]+)', content)
                        
                    if match:
                        return match.group(1)
            except Exception:
                pass
    
    return None


def sign_in_with_email_password(email: str, password: str) -> dict:
    """
    Sign in a user with email and password using Firebase REST API.
    
    Args:
        email: User's email address
        password: User's password
    
    Returns:
        dict with keys: success, user_id, email, id_token, error_message
    """
    
    api_key = _get_firebase_api_key()
    if not api_key:
        return {"success": False, "error_message": "Firebase API key not configured"}
    
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True
    }
    
    try:
        response = requests.post(url, json=payload)
        data = response.json()
        
        if response.status_code == 200:
            return {
                "success": True,
                "user_id": data.get("localId"),
                "email": data.get("email"),
                "display_name": data.get("displayName"),
                "id_token": data.get("idToken"),
                "error_message": None
            }
        else:
            error_msg = data.get("error", {}).get("message", "Unknown error")
            return {
                "success": False,
                "error_message": error_msg
            }
    except Exception as e:
        return {"success": False, "error_message": str(e)}


def sign_up_with_email_password(email: str, password: str) -> dict:
    """
    Sign up a new user with email and password using Firebase REST API.
    
    Args:
        email: User's email address
        password: User's password (min 6 characters)
    
    Returns:
        dict with keys: success, user_id, email, id_token, error_message
    """
    import requests
    
    api_key = _get_firebase_api_key()
    if not api_key:
        return {"success": False, "error_message": "Firebase API key not configured"}
    
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True
    }
    
    try:
        response = requests.post(url, json=payload)
        data = response.json()
        
        if response.status_code == 200:
            return {
                "success": True,
                "user_id": data.get("localId"),
                "email": data.get("email"),
                "id_token": data.get("idToken"),
                "error_message": None
            }
        else:
            error_msg = data.get("error", {}).get("message", "Unknown error")
            return {
                "success": False,
                "error_message": error_msg
            }
    except Exception as e:
        return {"success": False, "error_message": str(e)}
