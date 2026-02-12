import os
from datetime import datetime
from firebase_service import log_login_event

def test_firebase():
    print("Testing Firebase initialization and Firestore write...")
    
    # Check if service account file exists
    if os.path.exists('firebase_config.json'):
        print("✅ Found firebase-service-account.json")
    else:
        print("❌ firebase-service-account.json NOT found")
        return
    now = datetime.now()
    print(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    # Attempt to log a test event
    success = log_login_event(
        user_email=f"test-{now.strftime('%Y%m%d-%H%M%S')}@example.com",
        user_name="Test User",
        provider="diagnostic_test",
        user_id="test_id_123"
    )
    
    if success:
        print("✅ Successfully logged test event to Firestore!")
    else:
        print("❌ Failed to log test event. Check terminal for error messages.")

if __name__ == "__main__":
    test_firebase()
