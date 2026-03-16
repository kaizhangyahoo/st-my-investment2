---
name: remote-mcp
description: Interact with the remote Playwright MCP server at 192.168.1.201:8931 via direct HTTP calls. Use this skill whenever you need to control a remote browser via MCP, bypassing the agent's built-in MCP tool discovery (which is unreliable for remote SSE servers).
---

# Remote MCP Skill

## Background

The agent has a built-in `list_resources` / MCP tool that reads from `mcp.json`.
This tool is **unreliable** for remote SSE-based MCP servers — it often returns
`server name not found` even when the server is running correctly.

**Do NOT use `list_resources()` for the remote MCP server. Always use the
Python approach described below.**

## Server Details

| Property | Value |
|---|---|
| Host | `192.168.1.201` |
| Port | `8931` |
| Protocol | MCP over HTTP (Streamable HTTP transport) |
| Entry Point | `POST http://192.168.1.201:8931/mcp` |
| Session Init | Session ID returned in `mcp-session-id` response header |

## How to Use

### Step 1: Always use `run_command` with the Python helper script

Use the reference script at `.agent/skills/remote-mcp/scripts/mcp_client.py`.
This script handles:
- Session initialization
- Correct SSE response parsing (`event: message\ndata: {...}`)
- Persistent session ID across tool calls

### Step 2: MCP Tool Call Protocol

Every interaction with the server follows this sequence:

```
POST /mcp  →  initialize  →  get mcp-session-id header
POST /mcp  →  initialized notification (no response needed)
POST /mcp  →  tools/call or tools/list  →  parse SSE data: line
```

### Step 3: Parsing Responses

The server returns SSE-formatted responses. **Always skip `event: message`
lines and parse only lines starting with `data: `.**

```python
for line in resp.iter_lines():
    if line:
        decoded = line.decode().strip()
        if decoded.startswith("data: "):
            data = json.loads(decoded[6:])
            # process data here
            break
```

## Available Tools (Confirmed)

The MCP server exposes Playwright browser tools including (not exhaustive):
- `browser_navigate` — Navigate to a URL
- `browser_take_screenshot` — Take a PNG screenshot (returns base64)
- `browser_get_url` — Get current page URL
- `browser_evaluate` — Execute JavaScript in the page context
- `browser_click` — Click an element
- `browser_fill` — Fill an input field
- `browser_snapshot` — Get accessibility tree snapshot (YAML)

To get the full list at runtime, call `tools/list` via the script.

## Quick Usage Example

```bash
python3 .agent/skills/remote-mcp/scripts/mcp_client.py \
  --tool browser_navigate \
  --args '{"url": "http://192.168.1.201:8501"}'
```

For screenshots, the script saves to `/tmp/mcp_screenshot.png` by default.

## Reference Scripts

- `scripts/mcp_client.py` — General-purpose MCP client (navigate, screenshot, evaluate, list tools)
- `scripts/mcp_verify.sh` — Bash-based quick connectivity and session test

## Common Pitfalls

1. **Do NOT use `list_resources()` tool** — it will always fail for this server.
2. **Session IDs expire** — always initialize a new session per run; do not reuse IDs across script invocations.
3. **Screenshot tool name** — the tool is `browser_take_screenshot`, NOT `browser_screenshot`.
4. **Response format** — responses come as SSE (`event: message\ndata: {...}`), not plain JSON. Always parse the `data:` line.
5. **`aiohttp` is not installed** — use `requests` (the `mcp_client.py` script uses `requests`).
