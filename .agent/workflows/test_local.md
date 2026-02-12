---
description: Run Playwright tests against the local environment (localhost:8501)
---

1. Ensure the Streamlit app is running locally.
   > **Note:** You must have `streamlit run rewrite_login.py` running in a separate terminal before starting this workflow.

2. Run the Playwright tests targeting localhost.
   ```bash
   pytest .agent/skills/playwright_testing/examples
   ```
