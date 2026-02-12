---
description: Scan the codebase for potential secrets like API keys or private keys.
---

1. Run a search for common secret patterns across the repository.
   // turbo
   `grep -rE "AIza[0-9A-Za-z_-]{35}|xox[baprs]-[0-9]{12}-[0-9]{12}-[a-zA-Z0-9_-]{24}|SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}|AKIA[0-9A-Z]{16}|[0-9a-f]{32}-us[0-9]+|-----BEGIN (RSA|EC|PGP) PRIVATE KEY-----" . --exclude-dir={.git,.gemini,node_modules,venv,.venv}`

2. Check for common sensitive filenames.
   // turbo
   `find . -name ".env" -o -name "*.pem" -o -name "*.key" -o -name "firebase-service-account.json" | grep -v ".git"`

3. If any secrets are found, notify the user and suggest using `git filter-repo` or `BFG Repo-Cleaner` if they were already committed.
