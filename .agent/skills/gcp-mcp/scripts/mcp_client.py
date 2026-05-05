#!/usr/bin/env python3
import subprocess
import requests
import json
import sys
import argparse

MCP_URL = "https://developerknowledge.googleapis.com/mcp"

def get_access_token():
    """Fetch the GCP access token using gcloud."""
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token", "--scopes=https://www.googleapis.com/auth/cloud-platform"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error fetching token: {e.stderr}", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("gcloud command not found. Please install Google Cloud SDK.", file=sys.stderr)
        return None

def call_mcp(method, params=None, token=None):
    """Call the GCP MCP server."""
    if not token:
        token = get_access_token()
    
    if not token:
        return {"error": "Could not obtain access token"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }
    
    try:
        resp = requests.post(MCP_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def main():
    parser = argparse.ArgumentParser(description="GCP Developer Knowledge MCP Client")
    parser.add_argument("--list-tools", action="store_true", help="List available tools")
    parser.add_argument("--query", help="Short-cut for answer_query tool")
    parser.add_argument("--tool", help="Call a specific tool")
    parser.add_argument("--args", default="{}", help="JSON arguments for the tool")
    parser.add_argument("--stdio", action="store_true", help="Run as an MCP stdio server")
    
    args = parser.parse_args()
    
    if args.stdio:
        # Simple stdio bridge
        token = get_access_token()
        if not token:
            print("Error: Could not obtain access token", file=sys.stderr)
            sys.exit(1)
            
        for line in sys.stdin:
            try:
                request = json.loads(line)
                method = request.get("method")
                params = request.get("params", {})
                request_id = request.get("id")
                
                # Special handling for initialization
                if method == "initialize":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {}
                            },
                            "serverInfo": {
                                "name": "gcp-mcp-bridge",
                                "version": "1.0.0"
                            }
                        }
                    }
                elif method == "tools/list":
                    response = call_mcp("tools/list", token=token)
                    response["id"] = request_id
                elif method == "tools/call":
                    response = call_mcp("tools/call", params, token=token)
                    response["id"] = request_id
                else:
                    # Generic forward for other methods
                    response = call_mcp(method, params, token=token)
                    response["id"] = request_id
                
                print(json.dumps(response))
                sys.stdout.flush()
                
            except Exception as e:
                print(f"Error in stdio loop: {e}", file=sys.stderr)
        return
    
    if args.list_tools:
        result = call_mcp("tools/list")
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            tools = result.get("result", {}).get("tools", [])
            print(f"Found {len(tools)} tools:")
            for t in tools:
                print(f"  - {t['name']}: {t.get('description', '')[:100]}...")
    
    elif args.query:
        print(f"Answering query: {args.query}...")
        result = call_mcp("tools/call", {
            "name": "answer_query",
            "arguments": {"query": args.query}
        })
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            content = result.get("result", {}).get("content", [])
            for item in content:
                print(item.get("text", ""))
                
    elif args.tool:
        try:
            tool_args = json.loads(args.args)
        except json.JSONDecodeError:
            print("Error: --args must be valid JSON")
            return
            
        result = call_mcp("tools/call", {
            "name": args.tool,
            "arguments": tool_args
        })
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
