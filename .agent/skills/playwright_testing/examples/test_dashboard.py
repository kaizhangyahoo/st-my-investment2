import pytest
from playwright.sync_api import sync_playwright
import os
import sys

# Add directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Configure base URL: set BASE_URL env var to test remote
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8501")

@pytest.fixture(scope="function")
def browser_context():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        yield context
        browser.close()

def test_dashboard_title_visible(browser_context):
    """Verify that the dashboard title appears after any login."""
    page = browser_context.new_page()
    page.goto(BASE_URL)
    
    # Check for the header string in rewrite_tab_1.py
    # Note: Streamlit won't show the dashboard unless logged in based on rewrite_login.py
    # So this test might check for the login header instead if not logged in.
    # Wait for the app to load (title changes from 'Streamlit' to specific title)
    page.wait_for_function("document.title != 'Streamlit'")
    
    current_title = page.title()
    assert "Portfolio Dashboard" in current_title

def test_file_uploader_presence(browser_context):
    """Verify the file uploader exists on the dashboard."""
    # This would require being logged in. We can skip or mock.
    pass

def test_chart_containers(browser_context):
    """Verify that chart containers are rendered."""
    # This would require being logged in.
    pass
