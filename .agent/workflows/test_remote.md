---
description: Run Playwright tests against the deployed Cloud Run environment
---

1. Run the Playwright tests targeting the Cloud Run application.
   ```bash
   BASE_URL=https://streamlit-app-rj6qghjncq-uc.a.run.app pytest .agent/skills/playwright_testing/examples
   ```
