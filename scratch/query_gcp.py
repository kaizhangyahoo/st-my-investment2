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

query = "How to set a budget alert for a GCP billing account to £5, send notification at 50%, and setup a hard cap when it reaches £5 each month?"
print(f"Querying: {query}")

result = call_mcp("tools/call", {"name": "answer_query", "arguments": {"query": query}})
print(json.dumps(result, indent=2))
