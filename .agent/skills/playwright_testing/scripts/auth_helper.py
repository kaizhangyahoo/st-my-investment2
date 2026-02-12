import time

class AuthHelper:
    def __init__(self, page):
        self.page = page

    def login_with_email(self, email, password):
        """Perform email/password login."""
        # Ensure we are on the login page and not logged in
        self.page.wait_for_selector('h1:has-text("Portfolio Dashboard")')
        
        # Click "Sign In" tab/toggle if not already active
        # The toggle is a regular button, NOT a form submit
        # We can find it by filtering for one that is NOT a form submit
        signin_buttons = self.page.get_by_role("button", name="Sign In", exact=True).all()
        for btn in signin_buttons:
            # Check if this button is associated with a form
            # Streamlit form submit buttons usually have specific attributes or hierarchy
            # Simplest way: The toggle is usually first or we try to click the one that isn't the submit
            if "stBaseButton-secondaryFormSubmit" not in str(btn.get_attribute("data-testid")):
                 if btn.is_visible():
                     btn.click()
                     break
        
        # Fill credentials
        self.page.get_by_label("📧 Email").fill(email)
        self.page.get_by_label("🔒 Password").fill(password)
        
        # Submit form
        # The submit button definitely has the specific test ID for form submits
        submit_btn = self.page.locator('button[data-testid*="FormSubmit"]')
        # Filter for the one with text "Sign In" in case there are others
        submit_btn.filter(has_text="Sign In").click()
        
        # Wait for dashboard or error
        time.sleep(2) # Give it a moment to process

    def is_logged_in(self):
        """Check if user is logged in (sidebar shows Welcome message)."""
        welcome_text = self.page.locator("sidebar").get_by_text("Welcome")
        return welcome_text.is_visible()

    def logout(self):
        """Click the logout button."""
        logout_button = self.page.get_by_role("button", name="🚪 Logout")
        if logout_button.is_visible():
            logout_button.click()
            self.page.wait_for_selector('h1:has-text("Portfolio Dashboard")')
