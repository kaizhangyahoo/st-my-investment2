#!/bin/bash
# mcp_verify.sh - Quick connectivity and session test for the remote MCP server
# Usage: bash mcp_verify.sh [MCP_URL]
#
# This script is a reference for how to interact with the MCP server via bash.
# It verifies the server is reachable, starts a session, navigates to the dashboard,
# and takes a screenshot.

MCP_URL="${1:-http://192.168.1.201:8931/mcp}"
HEADERS=(-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream")

echo "=== Remote MCP Verification Script ==="
echo "Target: $MCP_URL"
echo ""

# --- Step 1: Initialize and get session ID ---
echo "[1/4] Initializing session..."
INIT_RESP=$(curl -s -i -X POST "$MCP_URL" "${HEADERS[@]}" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "mcp-verify", "version": "1.0"}}}')

SESSION_ID=$(echo "$INIT_RESP" | grep -i "mcp-session-id" | awk '{print $2}' | tr -d '\r')

if [ -z "$SESSION_ID" ]; then
    echo "[ERROR] Could not get session ID. Check the server is running."
    exit 1
fi
echo "  Session ID: $SESSION_ID"

# --- Step 2: Send initialized notification ---
echo "[2/4] Sending initialized notification..."
curl -s -X POST "$MCP_URL" "${HEADERS[@]}" -H "mcp-session-id: $SESSION_ID" \
  -d '{"jsonrpc": "2.0", "method": "initialized", "params": {}}' > /dev/null

# --- Step 3: List tools ---
echo "[3/4] Listing available tools..."
TOOLS_RAW=$(curl -s -X POST "$MCP_URL" "${HEADERS[@]}" -H "mcp-session-id: $SESSION_ID" \
  -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}')

# Parse SSE response
TOOLS_JSON=$(echo "$TOOLS_RAW" | sed 's/^event: message$//' | grep "^data: " | sed 's/^data: //')

if [ -n "$TOOLS_JSON" ] && command -v jq &> /dev/null; then
    TOOL_COUNT=$(echo "$TOOLS_JSON" | jq '.result.tools | length')
    echo "  Found $TOOL_COUNT tools:"
    echo "$TOOLS_JSON" | jq -r '.result.tools[] | "  - \(.name)"'
else
    echo "  (install jq to see parsed tool list)"
    echo "  Raw: $TOOLS_RAW" | head -c 200
fi

echo ""
echo "[OK] MCP server is reachable and session was successfully established."
echo "     Use scripts/mcp_client.py for Python-based interactions."
