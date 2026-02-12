# User Login Records (Firebase)

This skill tracks and retrieves user login events using Google Firebase Firestore.

## Features
- **Logging**: Automatically log user login events (email, provider, timestamp, name).
- **History Retrieval**: Fetch recent logins for a specific user or all users (admin).
- **Authentication Support**: Includes helper methods for Firebase Email/Password login.

## Directory Structure
- `firebase_service.py`: Core logic for Firestore operations.
- `scripts/check_recent_logins.py`: CLI tool to view recent login history.
- `scripts/firebase_config.json`: Firebase configuration (Service account key).
- `test_firebase_diag.py`: Diagnostic script to test connectivity.

## Setup
1. Ensure `firebase-admin` is installed:
   ```bash
   pip install firebase-admin
   ```
2. Place your Firebase service account JSON file at `.agent/skills/users-login-record-firebase/scripts/firebase_config.json`.
3. (Optional) Set `FIREBASE_CONFIG` environment variable as a JSON string for cloud deployments.

## Usage

### Check Recent Logins
To see who has logged in recently, run the check script from the skill's root directory:
```bash
python scripts/check_recent_logins.py
```

### Integration in Code
Import and use the service in your Python application:
```python
from firebase_service import log_login_event

# Log a successful login
log_login_event(
    user_email="user@example.com",
    user_name="John Doe",
    provider="google"
)
```

## Maintenance
Use `test_firebase_diag.py` to verify that Firestore writes are working correctly.
