---
name: gcp-mcp
description: Interact with the GCP Developer Knowledge MCP server at https://developerknowledge.googleapis.com/mcp. This skill automatically handles OAuth2 authentication using the local `gcloud` CLI.
---

# GCP MCP Skill

## Overview
This skill allows the agent to query the Google Cloud Developer Knowledge corpus. It uses the `gcloud auth print-access-token` command to obtain a temporary Bearer token for authentication.

## Tools Available
- `search_documents`: Search Google developer documentation (APIs, guides, etc.)
- `answer_query`: Get grounded answers to technical questions about GCP, Firebase, Android, and more.
- `get_documents`: Retrieve full markdown content of documentation.

## Usage

### Run a direct query (shortcut)
```bash
python3 .agent/skills/gcp-mcp/scripts/mcp_client.py --query "How to set a budget alert in GCP?"
```

### List all tools
```bash
python3 .agent/skills/gcp-mcp/scripts/mcp_client.py --list-tools
```

### Call a specific tool
```bash
python3 .agent/skills/gcp-mcp/scripts/mcp_client.py --tool search_documents --args '{"query": "cloud run terraform"}'
```

## Troubleshooting
- **Token expired/invalid**: Ensure you are logged in to gcloud via `gcloud auth login`.
- **gcloud not found**: Ensure the Google Cloud SDK is installed and in your PATH.
- **Quota errors**: `answer_query` has a limited quota; if it fails, use `search_documents` instead.
