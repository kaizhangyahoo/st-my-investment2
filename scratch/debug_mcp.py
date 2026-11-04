import requests
import json

url = "https://developerknowledge.googleapis.com/mcp"

def call_mcp(method, params=None):
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": method,
        "params": params or {}
    }
    resp = requests.post(url, json=payload)
    return resp.json()

print("Listing tools...")
result = call_mcp("tools/list")
print(json.dumps(result, indent=2))
