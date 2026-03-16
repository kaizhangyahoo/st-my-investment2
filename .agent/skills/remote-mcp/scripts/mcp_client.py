#!/usr/bin/env python3
"""
Remote MCP Client for Playwright MCP Server at 192.168.1.201:8931

Usage:
    # List all available tools
    python3 mcp_client.py --list-tools

    # Navigate to a URL
    python3 mcp_client.py --tool browser_navigate --args '{"url": "http://example.com"}'

    # Take a screenshot (saved to /tmp/mcp_screenshot.png)
    python3 mcp_client.py --tool browser_take_screenshot --args '{"type": "png"}'

    # Evaluate JS
    python3 mcp_client.py --tool browser_evaluate --args '{"code": "() => document.title"}'

    # Full flow: navigate then screenshot
    python3 mcp_client.py --navigate http://192.168.1.201:8501 --screenshot /tmp/dashboard.png
"""

import requests
import json
import base64
import time
import argparse
import sys
import os

MCP_URL = "http://192.168.1.201:8931/mcp"


def create_session(url=MCP_URL):
    """Initialize an MCP session and return the session object with ID set."""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    })

    # Initialize
    resp = session.post(url, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "remote-mcp-skill", "version": "1.0"}
        }
    }, stream=True)

    session_id = resp.headers.get('mcp-session-id')
    if session_id:
        session.headers.update({"mcp-session-id": session_id})

    # Consume initialization response
    for line in resp.iter_lines():
        if line:
            break
    resp.close()

    # Send initialized notification
    session.post(url, json={"jsonrpc": "2.0", "method": "initialized", "params": {}})

    return session, session_id


def call_tool(session, tool_name, arguments=None, url=MCP_URL, request_id=2):
    """Call an MCP tool and return the parsed result."""
    payload = {
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments or {}}
    }
    resp = session.post(url, json=payload, stream=True)
    result = None
    for line in resp.iter_lines():
        if line:
            decoded = line.decode().strip()
            if decoded.startswith("data: "):
                result = json.loads(decoded[6:])
                break
    resp.close()
    return result


def list_tools(session, url=MCP_URL):
    """List all available tools from the MCP server."""
    resp = session.post(url, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    }, stream=True)
    result = None
    for line in resp.iter_lines():
        if line:
            decoded = line.decode().strip()
            if decoded.startswith("data: "):
                result = json.loads(decoded[6:])
                break
    resp.close()
    return result


def save_screenshot(result, output_path="/tmp/mcp_screenshot.png"):
    """Extract and save a screenshot from a tool call result."""
    if not result:
        print("[ERROR] No result received.")
        return False
    content_list = result.get("result", {}).get("content", [])
    if content_list and content_list[0].get("text"):
        img_data = base64.b64decode(content_list[0]["text"])
        with open(output_path, "wb") as f:
            f.write(img_data)
        print(f"[OK] Screenshot saved to {output_path} ({len(img_data):,} bytes)")
        return True
    else:
        print(f"[WARN] No screenshot content found. Response: {json.dumps(result, indent=2)}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Remote Playwright MCP Client")
    parser.add_argument("--url", default=MCP_URL, help="MCP server URL")
    parser.add_argument("--list-tools", action="store_true", help="List all available tools")
    parser.add_argument("--tool", help="Tool name to call")
    parser.add_argument("--args", default="{}", help="JSON arguments for the tool call")
    parser.add_argument("--navigate", help="Navigate to this URL (shortcut)")
    parser.add_argument("--screenshot", help="Take a screenshot and save to this path")
    parser.add_argument("--wait", type=int, default=3, help="Seconds to wait after navigation before screenshot")

    args = parser.parse_args()

    print(f"[INFO] Connecting to {args.url}...")
    session, session_id = create_session(args.url)
    print(f"[INFO] Session ID: {session_id}")

    req_id = 2

    if args.list_tools:
        print("[INFO] Listing tools...")
        result = list_tools(session, args.url)
        if result:
            tools = result.get("result", {}).get("tools", [])
            print(f"\nFound {len(tools)} tools:\n")
            for t in tools:
                desc = t.get("description", "").replace("\n", " ")[:80]
                print(f"  - {t['name']}: {desc}")
        else:
            print("[ERROR] Could not retrieve tools list.")

    elif args.navigate:
        print(f"[INFO] Navigating to {args.navigate}...")
        result = call_tool(session, "browser_navigate", {"url": args.navigate}, args.url, req_id)
        req_id += 1
        if result:
            text = result.get("result", {}).get("content", [{}])[0].get("text", "")
            print(f"[OK] Navigation result:\n{text}")
        if args.screenshot:
            print(f"[INFO] Waiting {args.wait}s for page load...")
            time.sleep(args.wait)
            print("[INFO] Taking screenshot...")
            result = call_tool(session, "browser_take_screenshot", {"type": "png"}, args.url, req_id)
            save_screenshot(result, args.screenshot)

    elif args.tool:
        tool_args = json.loads(args.args)
        print(f"[INFO] Calling tool: {args.tool} with args: {tool_args}")
        result = call_tool(session, args.tool, tool_args, args.url, req_id)
        if result:
            content_list = result.get("result", {}).get("content", [])
            if args.tool == "browser_take_screenshot" and content_list:
                save_screenshot(result, "/tmp/mcp_screenshot.png")
            elif content_list:
                for item in content_list:
                    print(item.get("text", ""))
            else:
                print(json.dumps(result, indent=2))
        else:
            print("[ERROR] No result received.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
