import streamlit as st
import os
import sys
st.set_page_config(
    page_title="Portfolio Dashboard",
    page_icon="📈",
    layout="wide"
)

# Import Firebase service for login logging and email/password auth
sys.path.append(os.path.join(os.getcwd(), ".agent/skills/users-login-record-firebase/scripts"))

try:
    from firebase_service import log_login_event, sign_in_with_email_password, sign_up_with_email_password
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False

# Import streamlit-oauth for GitHub (custom OAuth flow)
try:
    from streamlit_oauth import OAuth2Component
    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False

# Environment-aware configuration
IS_REMOTE = os.environ.get("K_SERVICE") is not None
REMOTE_BASE_URL = "https://streamlit-app-rj6qghjncq-uc.a.run.app/"

def get_effective_redirect_uri():
    """Determine the correct redirect URI for the current environment."""
    if IS_REMOTE:
        return REMOTE_BASE_URL
    return st.secrets.get("auth", {}).get("redirect_uri", "http://localhost:8501")


def show_legal_page():
    """Display the Privacy Policy and User Data Deletion instructions."""
    st.title("⚖️ Legal & Privacy Information")
    st.markdown("---")
    
    st.markdown("""
    ### 1. Privacy Policy
    This application ("Portfolio Dashboard") values your privacy. This policy explains how we handle your information when you used our services.
    
    *   **Data Collection:** We only collect your email address, name, and profile picture provided by your chosen login provider (Google, GitHub, or Facebook) via OAuth.
    *   **Data Usage:** Your information is used strictly for authentication purposes and to personalize your dashboard experience.
    *   **Data Sharing:** We do not sell, trade, or otherwise transfer your personal information to outside parties.
    *   **Data Security:** We implement security measures to maintain the safety of your personal information.

    ---

    ### 2. User Data Deletion Instructions
    You have the right to request the deletion of your account and associated data at any time.
    
    To delete your data, please follow these steps:
    1.  Send an email to the developer at **kaizhang@yahoo.com** with the subject "Data Deletion Request".
    2.  Include the email address associated with your account.
    3.  We will process your request and delete all your data from our database within 72 hours.
    
    *Once deleted, your portfolio data and login history cannot be recovered.*
    """)
    
    st.markdown("")
    if st.button("⬅️ Back to Login", use_container_width=True):
        st.query_params.clear()
        st.rerun()
    st.stop()


# Check for legal page view via query parameters
try:
    # Use to_dict() to ensure compatibility and handle possible proxy/iframe issues
    params = st.query_params.to_dict()
    if params.get("view") == "legal":
        show_legal_page()
except Exception:
    # Fallback for older streamlit versions if necessary
    try:
        if "legal" in st.experimental_get_query_params().get("view", []):
            show_legal_page()
    except Exception:
        pass


def log_user_login(provider: str, email: str = None, user_name: str = None, user_id: str = None):
    """Log successful login to Firebase if available."""
    if FIREBASE_AVAILABLE:
        log_login_event(
            user_email=email or getattr(st.experimental_user, 'email', 'unknown'),
            user_name=user_name or getattr(st.experimental_user, 'name', None),
            provider=provider,
            user_id=user_id or getattr(st.experimental_user, 'sub', None),
        )


def handle_email_auth():
    """Handle email/password sign in or sign up."""
    if "auth_mode" not in st.session_state:
        st.session_state.auth_mode = "signin"
    
    # Toggle between sign in and sign up
    col_signin, col_signup = st.columns(2)
    with col_signin:
        if st.button("Sign In", use_container_width=True, 
                     type="primary" if st.session_state.auth_mode == "signin" else "secondary"):
            st.session_state.auth_mode = "signin"
            st.rerun()
    with col_signup:
        if st.button("Sign Up", use_container_width=True,
                     type="primary" if st.session_state.auth_mode == "signup" else "secondary"):
            st.session_state.auth_mode = "signup"
            st.rerun()
    
    st.markdown("")
    
    with st.form("email_auth_form"):
        email = st.text_input("📧 Email")
        password = st.text_input("🔒 Password", type="password")
        
        if st.session_state.auth_mode == "signin":
            submit_label = "Sign In"
        else:
            submit_label = "Create Account"
        
        submitted = st.form_submit_button(submit_label, use_container_width=True)
        
        if submitted:
            if not email or not password:
                st.error("Please enter both email and password.")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                if st.session_state.auth_mode == "signin":
                    result = sign_in_with_email_password(email, password)
                else:
                    result = sign_up_with_email_password(email, password)
                
                if result["success"]:
                    # Store user info in session state
                    st.session_state.email_user = {
                        "email": result["email"],
                        "user_id": result["user_id"],
                        "display_name": result.get("display_name"),
                        "id_token": result["id_token"]
                    }
                    st.session_state.login_logged = False  # Trigger login logging
                    st.success(f"✅ {'Welcome back' if st.session_state.auth_mode == 'signin' else 'Account created'}! Redirecting...")
                    st.rerun()
                else:
                    error_msg = result["error_message"]
                    # Make error messages more user-friendly
                    if "EMAIL_NOT_FOUND" in error_msg:
                        st.error("No account found with this email. Try signing up instead.")
                    elif "INVALID_PASSWORD" in error_msg or "INVALID_LOGIN_CREDENTIALS" in error_msg:
                        st.error("Incorrect password. Please try again.")
                    elif "EMAIL_EXISTS" in error_msg:
                        st.error("An account with this email already exists. Try signing in.")
                    elif "WEAK_PASSWORD" in error_msg:
                        st.error("Password is too weak. Use at least 6 characters.")
                    else:
                        st.error(f"Authentication failed: {error_msg}")


def is_user_logged_in():
    """Check if user is logged in via any method."""
    # Check native Streamlit auth (Google OIDC)
    # Note: st.experimental_user.is_logged_in only works on Streamlit Community Cloud
    # On Cloud Run, we need to handle the case where this attribute doesn't exist
    try:
        if getattr(st.experimental_user, 'is_logged_in', False):
            return True
    except AttributeError:
        pass
    # Check email/password auth
    if "email_user" in st.session_state and st.session_state.email_user:
        return True
    # Check GitHub OAuth
    if "github_user" in st.session_state and st.session_state.github_user:
        return True
    # Check Facebook OAuth
    if "facebook_user" in st.session_state and st.session_state.facebook_user:
        return True
    return False


def get_current_user():
    """Get current user info from any auth method."""
    # Check native Streamlit auth (Google OIDC)
    try:
        if getattr(st.experimental_user, 'is_logged_in', False):
            return {
                "email": st.experimental_user.email,
                "name": getattr(st.experimental_user, 'name', st.experimental_user.email),
                "provider": "google"
            }
    except AttributeError:
        pass
    if "email_user" in st.session_state and st.session_state.email_user:
        user = st.session_state.email_user
        return {
            "email": user["email"],
            "name": user.get("display_name") or user["email"].split("@")[0],
            "provider": "email"
        }
    if "github_user" in st.session_state and st.session_state.github_user:
        user = st.session_state.github_user
        return {
            "email": user.get("email", "github_user"),
            "name": user.get("login", "GitHub User"),
            "provider": "github"
        }
    if "facebook_user" in st.session_state and st.session_state.facebook_user:
        user = st.session_state.facebook_user
        return {
            "email": user.get("email", "facebook_user"),
            "name": user.get("name", "Facebook User"),
            "provider": "facebook"
        }
    return None


def logout():
    """Logout from all auth methods."""
    try:
        if getattr(st.experimental_user, 'is_logged_in', False):
            st.logout()
    except AttributeError:
        pass
    st.session_state.pop("email_user", None)
    st.session_state.pop("github_user", None)
    st.session_state.pop("facebook_user", None)
    st.session_state.pop("login_logged", None)
    st.rerun()


# Check if user is logged in
if not is_user_logged_in():
    # Custom CSS for beautiful login page
    st.markdown("""
    <style>
    .main {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
    
    .login-container {
        max-width: 450px;
        margin: 0 auto;
        padding: 2rem;
    }
    
    .login-header {
        text-align: center;
        margin-bottom: 2rem;
    }
    
    .login-header h1 {
        font-size: 2.5rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    .login-header p {
        color: #a0a0a0;
        font-size: 1.1rem;
    }
    
    .divider {
        display: flex;
        align-items: center;
        text-align: center;
        margin: 1.5rem 0;
        color: #666;
    }
    
    .divider::before,
    .divider::after {
        content: '';
        flex: 1;
        border-bottom: 1px solid #333;
    }
    
    .divider span {
        padding: 0 1rem;
        font-size: 0.9rem;
    }
    
    .footer-text {
        text-align: center;
        color: #666;
        font-size: 0.85rem;
        margin-top: 2rem;
    }
    
    .feature-list {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 1.5rem;
        margin-top: 2rem;
    }
    
    .feature-item {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.75rem;
        color: #ccc;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Centered layout
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        # Header
        st.markdown("""
        <div class="login-header">
            <h1>📈 Portfolio Dashboard</h1>
            <p>Track your investments with powerful analytics</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("### Welcome! Sign in to continue")
        st.markdown("")
        
        # OAuth Providers Section
        st.markdown("#### Continue with")
        
        # Google Sign In Button (native OIDC)
        if st.button("🔵  Continue with Google", use_container_width=True, key="google_login"):
            st.login("google")
        
        st.markdown("")
        
        # GitHub Sign In using streamlit-oauth
        if OAUTH_AVAILABLE:
            github_client_id = st.secrets.get("auth", {}).get("github", {}).get("client_id")
            github_client_secret = st.secrets.get("auth", {}).get("github", {}).get("client_secret")
            
            if github_client_id and github_client_secret:
                # Use the environment-aware redirect URI
                github_redirect = get_effective_redirect_uri()
                
                oauth2 = OAuth2Component(
                    client_id=github_client_id,
                    client_secret=github_client_secret,
                    authorize_endpoint="https://github.com/login/oauth/authorize",
                    token_endpoint="https://github.com/login/oauth/access_token",
                )
                
                result = oauth2.authorize_button(
                    name="Continue with GitHub",
                    icon="https://github.githubassets.com/favicons/favicon.svg",
                    redirect_uri=github_redirect,
                    scope="user:email",
                    key="github_oauth",
                    use_container_width=True,
                )
                
                if result and "token" in result:
                    # Fetch user info from GitHub API
                    import requests
                    token = result["token"]["access_token"]
                    headers = {"Authorization": f"token {token}"}
                    try:
                        user_response = requests.get("https://api.github.com/user", headers=headers)
                        if user_response.status_code == 200:
                            github_user = user_response.json()
                            st.session_state.github_user = github_user
                            st.session_state.login_logged = False
                            print(f"✅ GitHub login successful for: {github_user.get('login')}")
                            st.rerun()
                        else:
                            st.error(f"Failed to fetch GitHub user info: {user_response.text}")
                            print(f"❌ GitHub API error: {user_response.status_code} - {user_response.text}")
                    except Exception as e:
                        st.error(f"GitHub Auth Error: {str(e)}")
                        print(f"❌ GitHub Exception: {e}")
            else:
                st.button("⚫  Continue with GitHub (Not Configured)", use_container_width=True, disabled=True)
        else:
            st.button("⚫  Continue with GitHub (Module Missing)", use_container_width=True, disabled=True)
        
        st.markdown("")
        
        # Facebook Sign In using streamlit-oauth
        if OAUTH_AVAILABLE:
            facebook_client_id = st.secrets.get("auth", {}).get("facebook", {}).get("client_id")
            facebook_client_secret = st.secrets.get("auth", {}).get("facebook", {}).get("client_secret")
            
            # Check for valid ID and Secret
            is_valid_id = facebook_client_id and isinstance(facebook_client_id, str) and not facebook_client_id.startswith("REPLACE")
            is_valid_secret = facebook_client_secret and isinstance(facebook_client_secret, str) and not facebook_client_secret.startswith("REPLACE")

            if is_valid_id and is_valid_secret:
                # Facebook OAuth with streamlit-oauth needs the BASE URL only (no /oauth2callback)
                # The library handles its own callback endpoint
                if IS_REMOTE:
                    facebook_redirect = REMOTE_BASE_URL
                else:
                    facebook_redirect = "http://localhost:8501/"
                
                facebook_oauth = OAuth2Component(
                    client_id=facebook_client_id,
                    client_secret=facebook_client_secret,
                    authorize_endpoint="https://facebook.com/dialog/oauth/",
                    token_endpoint="https://graph.facebook.com/oauth/access_token",
                )
                
                fb_result = facebook_oauth.authorize_button(
                    name="Continue with Facebook",
                    icon="https://www.facebook.com/favicon.ico",
                    redirect_uri=facebook_redirect,
                    scope="email,public_profile",
                    key="facebook_oauth",
                    use_container_width=True,
                )
                
                if fb_result and "token" in fb_result:
                    # Fetch user info from Facebook Graph API
                    import requests
                    token = fb_result["token"]["access_token"]
                    try:
                        user_response = requests.get(
                            "https://graph.facebook.com/me",
                            params={"fields": "id,name,email,picture", "access_token": token}
                        )
                        if user_response.status_code == 200:
                            facebook_user = user_response.json()
                            st.session_state.facebook_user = facebook_user
                            st.session_state.login_logged = False
                            print(f"✅ Facebook login successful for: {facebook_user.get('name')}")
                            st.rerun()
                        else:
                            st.error(f"Failed to fetch Facebook user info: {user_response.text}")
                            print(f"❌ Facebook API error: {user_response.status_code} - {user_response.text}")
                    except Exception as e:
                        st.error(f"Facebook Auth Error: {str(e)}")
                        print(f"❌ Facebook Exception: {e}")
            else:
                st.button("🔵  Continue with Facebook (Not Configured)", use_container_width=True, disabled=True)
        else:
            st.button("🔵  Continue with Facebook (Module Missing)", use_container_width=True, disabled=True)
        
        st.markdown("")
        st.markdown("""
        <div class="divider"><span>or use email</span></div>
        """, unsafe_allow_html=True)
        
        # Email/Password Section
        if FIREBASE_AVAILABLE:
            handle_email_auth()
        else:
            st.warning("Email/Password login requires Firebase configuration.")
        
        # Features
        st.markdown("""
        <div class="feature-list">
            <div class="feature-item">✅ View your complete portfolio</div>
            <div class="feature-item">📊 Interactive performance charts</div>
            <div class="feature-item">💹 Real-time market data</div>
            <div class="feature-item">🔒 Your data stays private</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(
            "By signing in, you agree to our [Privacy Policy](/?view=legal).  \n"
            "Authentication powered by secure OAuth 2.0",
            unsafe_allow_html=True # Keep for classes but use markdown for link
        )


else:
    # User is logged in
    user = get_current_user()
    
    # Log the login event (once per session)
    if "login_logged" not in st.session_state or not st.session_state.login_logged:
        st.session_state.login_logged = True
        if user and FIREBASE_AVAILABLE:
            log_user_login(
                provider=user["provider"],
                email=user["email"],
                user_name=user["name"]
            )
    
    # Sidebar with user info
    with st.sidebar:
        st.markdown(f"**Welcome, {user['name']}!**")
        st.caption(f"📧 {user['email']}")
        st.caption(f"🔐 Signed in via {user['provider'].title()}")
        st.markdown("---")
        if st.button("🚪 Logout", use_container_width=True):
            logout()
    
    # Execute the main dashboard
    exec(open("rewrite_tab_1.py").read())
