import sys
import os
from datetime import datetime

# Add the parent directory to sys.path so we can import firebase_service
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from firebase_service import get_all_login_history
except ImportError:
    print("Error: Could not import firebase_service. Make sure you are running this from the correct directory.")
    sys.exit(1)

def main():
    print("--- Recent User Logins ---")
    
    # Change CWD to the parent directory where firebase_config.json or the service expects things
    # Actually, the firebase_service.py searches for firebase_config.json in current directory.
    # Let's see if we need to change dir.
    
    # Try to fetch history
    history = get_all_login_history(limit=20)
    
    if not history:
        print("No login history found or Firebase not configured.")
        return

    # Print header
    print(f"{'Time (UTC)':<20} | {'Email':<30} | {'Provider':<15} | {'Name'}")
    print("-" * 80)
    
    for record in history:
        ts = record.get('timestamp')
        # If it's a Firestore datetime object, it might have a different format
        if hasattr(ts, 'strftime'):
            ts_str = ts.strftime('%Y-%m-%d %H:%M:%S')
        else:
            ts_str = str(ts)
            
        email = record.get('email', 'N/A')
        provider = record.get('provider', 'N/A')
        name = record.get('name', '')
        
        print(f"{ts_str:<20} | {email:<30} | {provider:<15} | {name}")

if __name__ == "__main__":
    main()
