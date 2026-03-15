# IG Trade & Transactions Playwright Skill

Short description
- A small CLI-like Python script that uses Playwright to log into an IG account, navigate the "History" area in the web platform, and download two types of CSV/history files (trade history and transactions) into the user's `~/Downloads` folder.

Prerequisites
- Python
- Playwright Python package installed: `pip install playwright`
- Playwright browsers installed: `playwright install`
- A valid IG account username configured in the script (see `USERNAME` constant) and the account password supplied at runtime.

Location
- Script path: `.agent/skills/get_ig_trade_and_transaction_history/scripts/playwright_get_trade_transaction_history.py`

Behavior summary
- Launches a Chromium browser (by default: `headless=True`).
- Accepts the cookie banner and navigates to the IG login flow.
- Fills the username configured in the script and prompts for the password (or accepts `--password`).
- After successful login it opens the platform, navigates to History → View full history in My IG, sets a custom date range, and downloads the Trade History CSV.
- It then navigates to the Transactions tab and performs up to two transaction downloads (matching the original flows).
- Both downloads are saved into `~/Downloads` and the saved file paths are printed at the end.
- **Sync to RPI**: A separate bash script `scripts/sync_to_rpi.sh` is provided for reference to transfer the latest history files to your Raspberry Pi, using the `SYNC_DESTINATION` configured in your `.env`.

CLI / Usage
- Run and follow the password prompt:

```bash
python scripts/playwright_get_trade_transaction_history.py
```

- Provide password on command line (less secure):

```bash
python scripts/playwright_get_trade_transaction_history.py --password mypassword
```

- Skip the transactions download if you only want trade history:

```bash
python scripts/playwright_get_trade_transaction_history.py --skip-transactions
```

- **Sync to Raspberry Pi**:
After downloading, you can sync the latest files using the helper script:

```bash
bash scripts/sync_to_rpi.sh
```

- **Sync from a custom directory**:
If you downloaded the files to a custom directory using the python script, pass the same path to the sync script:

```bash
bash scripts/sync_to_rpi.sh --download-dir /path/to/my/downloads
```

Options
- `-p, --password`: IG account password (will prompt if not provided).
- `--skip-transactions`: Only run the trade-history flow and skip the transactions flow.

Outputs
- Files saved to the user Downloads folder with the original suggested filenames from the IG website. The script prints the saved paths when downloads complete.

Configuration notes
- A `.env` file can be placed in `scripts/.env` with `IG_USERNAME` and `IG_PASSWORD`.
- `SYNC_DESTINATION` (e.g. `kaizhang@192.168.1.201:./Downloads`) can also be added as a hint for the agent to use when performing a manual sync.
- Username is stored in the script as a fallback, but the `.env` value will override. Change this to use a different account, or modify the script to read a username from an environment variable or arguments.

Error handling & common issues
- Login failures: the script contains checks for common login failure messages (incorrect username/password and "attempts left" messages). If login fails the script will print an error and exit.
- Selector fragility: the IG website may change element IDs/classes and test ids. If the script stops finding elements, update selectors in the script (the key areas are cookie accept button, login form fields, history navigation links, and DownloadHistoryButton test id).
- Playwright not installed: run `pip install playwright` and `playwright install`.
- Downloads stuck or not saved: ensure Playwright can access `~/Downloads` and the browser instance is allowed to save files (some environments sandbox downloads).

Security & privacy
- Do not store passwords in source control. Prefer the interactive prompt or a secure credential store.
- Downloaded CSVs may contain sensitive account/trade information — handle and store them securely.

Examples
- Download both files (will prompt for password):

```bash
python scripts/playwright_get_trade_transaction_history.py
```

- Non-interactive password (CI or automation — be aware of security implications):

```bash
python scripts/playwright_get_trade_transaction_history.py --password "S3cr3t"
```

Maintenance
- If IG changes its UI update the script selectors accordingly.
- Consider adding environment-based configuration (username, download dir) and optional headless mode.

Contact / Author
- Created/maintained within this repository under `.agent/skills/get_ig_trade_and_transaction_history`.
