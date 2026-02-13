import pytest
from playwright.sync_api import sync_playwright, expect
import os
import sys

# Add scripts directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.auth_helper import AuthHelper

# Configure base URL: set BASE_URL env var to test remote
# Default: http://localhost:8501
# Remote: https://streamlit-app-rj6qghjncq-uc.a.run.app
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8501")

@pytest.fixture(scope="function")
def browser_context():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        yield context
        browser.close()

def test_login_page_loads(browser_context):
    """Verify the login page renders correctly."""
    page = browser_context.new_page()
    page.goto(BASE_URL)
    
    # Check for main title
    expect(page.locator('h1:has-text("Portfolio Dashboard")')).to_be_visible()
    
    # Check for login options
    # Note: Double space after emoji in the app
    expect(page.get_by_role("button", name="🔵  Continue with Google")).to_be_visible()
    # Check that at least one Sign In button is visible (tab or form)
    expect(page.get_by_role("button", name="Sign In").first).to_be_visible()

def test_email_login_form_validation(browser_context):
    """Verify that email/password fields respond to input."""
    page = browser_context.new_page()
    page.goto(BASE_URL)
    
    auth = AuthHelper(page)
    
    # Try logging in with empty fields
    page.locator('button[data-testid*="FormSubmit"]').filter(has_text="Sign In").click()
    
    # Wait for and verify error message
    expect(page.get_by_text("Please enter both email and password")).to_be_visible()

@pytest.mark.skip(reason="Requires running app and valid test user")
def test_successful_email_login(browser_context):
    """Verify login with valid credentials."""
    page = browser_context.new_page()
    page.goto(BASE_URL)
    
    auth = AuthHelper(page)
    auth.login_with_email("test@example.com", "validpassword")
    
    # Verify redirect/sidebar change
    assert auth.is_logged_in()
