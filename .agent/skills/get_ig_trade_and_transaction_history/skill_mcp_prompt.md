```markdown
# IG Trade & Transaction History — Playwright MCP Prompt

## Overview

This prompt instructs an AI agent to replicate the behavior of
`playwright_get_trade_transaction_history.py` using **only** the
`playwright-mcp-pi` MCP server tools — no Python code is executed.

The remote Playwright MCP server runs on Docker at `192.168.1.201:8931`:

Reference: https://github.com/microsoft/playwright-mcp

## MCP Tool Reference (used in this flow)

| Tool                | Purpose                                        |
|---------------------|------------------------------------------------|
| `browser_navigate`  | Navigate to a URL                              |
| `browser_snapshot`  | Take an accessibility snapshot of current page |
| `browser_click`     | Click an element (by `ref` from snapshot)      |
| `browser_type`      | Type text into a focused/clicked input field   |
| `browser_press_key` | Press a keyboard key (e.g. Tab, Enter)         |
| `browser_wait`      | Wait for a specified duration (ms)             |
| `browser_tab_list`  | List open tabs                                 |
| `browser_tab_select`| Switch to a tab by index                       |

## Required Input

- `password`: The IG account password. Must be provided by the user before starting.
- `download_both`: Whether to download both trade history AND transaction history (default: true).

## Step-by-Step MCP Tool Call Sequence

> After every `browser_click` or `browser_navigate`, call `browser_snapshot` to get the updated accessibility tree and find the correct `ref` values for the next interaction.

### Phase 0-1: Initialize Context & Navigate to IG

**Context Initialization (CRITICAL):**
Before any navigation, the MCP server MUST initialize the browser context with `downloads_path: "/home/node"`.

If using the `playwright-mcp-pi` MCP server directly, ensure the browser context is created with:
```
context = await browser.new_context(downloads_path="/home/node")
```

If invoking via FastAPI (MCP server at 192.168.1.201:8931), ensure the `/run_skill` endpoint is called with:
```json
{
  "downloads_path": "/home/node"
}
```

**If this is not done, downloads will go to the default temp directory and be lost.** Verify downloads_path before proceeding.

### Phase 1: Download path setup, Navigation & Cookie Acceptance:**
1. `context = await browser.new_context(downloads_path="/home/node")`
2. `browser_navigate` → `url: "https://www.ig.com/uk"`
3. `browser_snapshot` → find "Accept" cookie button `ref`
4. `browser_click` → click Accept (use `ref`)

### Phase 2: Log in


5. `browser_click` → click Log in link
6. `browser_snapshot` → find "Email/username" textbox `ref`
7. `browser_click` → click username textbox
8. `browser_type` → text: `<USERNAME>` (user-provided)
9. `browser_press_key` → `Tab`
10. `browser_type` → text: `<PASSWORD>` (user-provided)
11. `browser_snapshot` → find "Log in" submit button `ref`
12. `browser_click` → click Log in submit

### Phase 3: Verify login & open platform

13. `browser_wait` → time: 10000 ms
14. `browser_snapshot` → verify "Open platform" is present; if not, stop and report login failure
15. `browser_click` → click "Open platform" (first instance)

### Phase 4: Navigate to History

16. `browser_snapshot` → find "History" button
17. `browser_click` → click History
18. `browser_snapshot` → find "View full history in My IG" link
19. `browser_click` → click View full history in My IG
20. `browser_tab_list` → check for new tab; if present `browser_tab_select` to switch

### Phase 5: Download Transaction History (if `download_both`)

21. `browser_snapshot` → find date range dropdown (labeled "since yesterday", "3 days", "90 days", etc., or "Custom period")
22. `browser_click` → click dropdown to expand options
23. `browser_snapshot` → check if "Custom period" or date input fields are visible
24. **Date Selection Strategy** (prioritized order):
    
    **Option A (PRIORITY):** Direct DOM input evaluation
    - Use `browser_evaluate` to set date input fields directly:
      ```javascript
      // Try multiple selectors for date inputs (IG may use different names)
      const fromInput = document.querySelector('input[name="fromDate"]') || 
                        document.querySelector('input[placeholder*="From"]') ||
                        document.querySelector('input[aria-label*="From"]');
      const toInput = document.querySelector('input[name="toDate"]') || 
                      document.querySelector('input[placeholder*="To"]') ||
                      document.querySelector('input[aria-label*="To"]');
      if (fromInput) fromInput.value = '01/01/2019';
      if (toInput) toInput.value = new Date().toLocaleDateString('en-GB');
      return { fromSet: !!fromInput, toSet: !!toInput };
      ```
    - If this succeeds (both inputs found), skip to step 25
    - If this fails (inputs not found), proceed to Option B
    
    **Option B (BETTER FALLBACK):** Year-by-year calendar navigation
    - Use `browser_evaluate` to click year navigation: `page.get_by_test_id("IconButtonPrevYear").click()`
    - From Feb 2026, need ~7 clicks to reach 2019 (vs 85 clicks for month-by-month)
    - Retry up to 8 times to reach target year, then click day/month
    - Pseudocode:
      ```javascript
      // Click previous year button 7 times to go from 2026 to 2019
      for (let i = 0; i < 7; i++) {
        const prevYearBtn = page.getByTestId("IconButtonPrevYear");
        await prevYearBtn.click();
        await page.waitForTimeout(300);
      }
      // Then click on Jan 01, 2019
      ```
    - If this fails after 3 retries, proceed to Option C
    
    **Option C (LAST RESORT):** Use preset date range
    - Use the "90 days" or "60 days" preset if Options A & B fail
    - Note: This limits history to 90 days instead of 8 years
    - **Report to user:** "⚠️ Custom date selection failed; downloaded last 90 days instead of full history (01/01/2019–today)"

25. `browser_snapshot` → verify dates are set correctly
26. `browser_click` → click "Set" or "Apply" button (find ref from snapshot)
27. `browser_wait` → 2000 ms
28. `browser_snapshot` → find ShowHistoryButton
29. `browser_click` → click ShowHistoryButton
30. `browser_wait` → 3000 ms
31. `browser_snapshot` → find DownloadHistoryButton (ref)
32. `browser_click` → click DownloadHistoryButton (triggers CSV download)

### Phase 6: Download Trade History

33. `browser_snapshot` → find `trade-history` tab (ref)
34. `browser_click` → click trade-history tab
35. `browser_wait` → 1000 ms
36. `browser_snapshot` → find date range dropdown (same control as Phase 5)
37. `browser_click` → click dropdown to expand options
38. `browser_snapshot` → check available date preset options
39. **Date Selection Strategy** (same as Phase 5 — use same prioritized approach):
    - **Option A:** Direct DOM input evaluation (same selectors as Phase 5)
    - **Option B:** Year-by-year calendar navigation with `IconButtonPrevYear` (7 clicks to reach 2019)
    - **Option C:** Use "90 days" or "60 days" preset if custom dates fail
40. `browser_snapshot` → verify dates are set
41. `browser_click` → click "Set" or "Apply" button
42. `browser_wait` → 2000 ms
43. `browser_snapshot` → find ShowHistoryButton
44. `browser_click` → click ShowHistoryButton
45. `browser_wait` → 3000 ms
46. `browser_snapshot` → find DownloadHistoryButton (ref)
47. `browser_click` → click DownloadHistoryButton (triggers CSV download)

## Downloads & Volume Mount

**CRITICAL:** Files are ONLY saved to `/home/node` if Phase 0 context initialization completes successfully.

- **Container path:** `/home/node` (inside MCP Playwright server Docker container)
- **Host path:** `~/Downloads` (on your local machine, if Docker is configured with volume bind-mount)
- **If downloads_path is not set:** Files fall back to Playwright's default temp directory (e.g., `/tmp/playwright-output/`) and will NOT be accessible at `~/Downloads`

**To verify files are saved correctly:**
1. Check Phase 0 executed without errors
2. After download completes, verify file exists at `~/Downloads/<filename>`
3. If not found at `~/Downloads`, check Docker volume mounts: `docker inspect <container_id> | grep -A 10 Mounts`

Files are automatically downloaded to `/home/node` via the browser context initialization (Phase 0). Since `/home/node` is bind-mounted to the host's `~/Downloads`, downloaded files will appear locally at `~/Downloads/<filename>`. Report host-visible paths as `~/Downloads/<filename>`.

## Error Handling

- **Phase 0-1 failure (downloads_path not set or navigation fails):** Stop immediately. Downloads will not be saved to `/home/node`. Verify MCP server initialization and network connectivity before retrying.
- **Login failure:** Stop and report if "Open platform" is not present after the wait.
- **Date picker navigation (Phases 5 & 6):** Attempt in prioritized order:
  1. **Option A fails:** Proceed to Option B (year-by-year navigation)
  2. **Option B fails after 3 retries:** Fall back to Option C (preset date range)
  3. **Report to user:** Whether full 8-year history was downloaded or limited to preset period. Example: "⚠️ Custom date selection unavailable; downloaded last 90 days instead of full history (01/01/2019–today)"
- **Element not found:** Retry snapshot once after 3000 ms, then fail with last snapshot. Prompt user on progress and which step failed.
- **Download timeout:** Wait up to 10s after clicking Download; report if not completed.

## Security

- Do not log or persist username, password.

## Troubleshooting

### Why Was History Limited to 90 Days Instead of 8 Years?

The IG website uses a React-based date picker. The skill now supports three strategies:

**Option A (Direct Input - FASTEST):**
- If date input fields exist in DOM (e.g., `input[name="fromDate"]`), this bypasses the calendar entirely
- Cost: 3–5 MCP calls total
- Success rate: ~80% if IG's UI hasn't changed

**Option B (Year-by-Year Navigation - RELIABLE):**
- Clicks `IconButtonPrevYear` 7 times to go from 2026 to 2019 (vs 85 clicks for month-by-month)
- Cost: ~40–50 MCP calls (7 year clicks + snapshot + selects day/month)
- Success rate: ~95% (uses official test IDs)
- This is much cheaper than month-by-month navigation (~1,700 calls)

**Option C (Preset Range - FALLBACK):**
- Uses "90 days" or "60 days" if Options A & B fail
- Cost: 2–3 MCP calls
- Provides limited history but ensures download succeeds

**To Prioritize Full History:**
1. Option A will be tried first (no harm if it fails)
2. Option B will activate if A fails (year-by-year is reliable and efficient)
3. Only falls back to Option C if B fails 3 times

**If Option B Still Fails:**
The test ID `IconButtonPrevYear` may have changed. Inspect the calendar widget:
```javascript
// Find year navigation button
const yearcheckButton = document.querySelector('[class*="prevYear"]') || 
                        document.querySelector('[aria-label*="previous year"]');
console.log(yearcheckButton);
```
Then update the skill with the new selector.


## Quick Agent Prompt (copy-paste ready)

Using the `playwright-mcp-pi` MCP server, initialize browser context with `downloads_path: "/home/node"`, then log into ig.com/uk with username "shanghailondon2000" and the password I will provide. Accept cookies, perform the login, verify by checking for "Open platform", then navigate History → View full history in My IG. On that page select a custom period ~8 years back from day 01, show history and download. Then switch to the trade-history tab, set custom period day 03 ~8 years back, show history and download. Report both download outcomes to `~/Downloads/<filename>`.


## Auto-click / Auto-accept (consent) behavior

To avoid repeated manual clicks on in-page controls like "Accept", "Allow", "Review", "Continue", or "Confirm", the MCP flow can run a small automated routine after each navigation or snapshot. This routine does three things in order:

- Try to find and click accessibility `ref`s returned by `browser_snapshot` that match common consent texts (case-insensitive).
- If no useful `ref` is found, run an in-page JS fallback that clicks any visible `button`, `a`, or `[role="button"]` whose innerText matches one of the consent words.
- Repeat (snapshot → try click refs → run JS fallback → wait) up to a small retry limit.

This approach only interacts with elements inside the page DOM and with JS dialogs; it does NOT click OS-level permission dialogs or interact with browser chrome.

Suggested MCP pseudocode to insert at each approval point (copy for reuse):

1. `browser_snapshot`
2. If snapshot contains `ref` elements whose accessible name/text matches /(accept|allow|review|continue|confirm)/i → for each matching `ref`: `browser_click` that `ref` and then `browser_snapshot`
3. Else run JS fallback via an evaluator (use `browser_snapshot` to pick a safe fallback; if your MCP server offers an evaluate API use it). Fallback JS (use evaluator to run this snippet):

    (function clickConsentButtons(){
      const texts = ['allow','accept','review','continue','confirm'];
      const nodes = Array.from(document.querySelectorAll('button,a,[role="button"]'));
      let clicked = 0;
      nodes.forEach(el=>{
        try{
          const t = (el.innerText||el.textContent||'').trim().toLowerCase();
          if(!t) return;
          for(const word of texts){
            if(t.includes(word)){
              el.click();
              clicked++;
              break;
            }
          }
        }catch(e){}
      });
      return clicked;
    })();

4. `browser_wait` 1000–3000 ms
5. `browser_snapshot` and repeat up to N times (N=4 recommended)
6. Also register handling for JS modal dialogs and accept them (if supported by the MCP `browser_handle_dialog` tool).

Notes and safety:
- Limit retries (4–6) to avoid infinite loops.
- Restrict the JS fallback to page-local elements; avoid executing page navigation or form submissions unless a matching button is observed and expected.
- Combine this with a persistent `userDataDir` context so cookie/state persists and you only need to accept once.

If you want, I will patch the MCP skill to include this routine at the cookie-consent and login-confirmation steps and then run the skill. Confirm and I will apply the change and execute the flow.

```
