---
name: cloud-deployer
description: Deploys Streamlit to GCP Cloud Run. Auto-detects the entry point and enforces Free Tier limits.
---

# Goal
Identify the main Streamlit entry point, containerize it, and deploy to GCP Cloud Run (us-central1).

# Instructions

## 1. Discovery & Entry Point
- **Scan Files:** Search for all `.py` files in the root directory.
- **Identify Main App:** Look for the file containing `import streamlit as st`.
- **User Confirmation:** If multiple files are found, ASK the user: "I found multiple Python files. Which one is your main Streamlit entry point?"
- **Variable Storage:** Store the chosen filename as `ENTRY_POINT`.

## 2. Environment Verification
- Check if `terraform` is installed via `which terraform`.
- If missing, suggest: `brew install terraform`.
- Verify GCP Project: `gcloud config get-value project`.

## 3. Deployment Artifacts
- **Dockerfile:** Generate a Dockerfile.
  - USE the `ENTRY_POINT` variable: `CMD ["streamlit", "run", "${ENTRY_POINT}", "--server.port=8080", "--server.address=0.0.0.0"]`.
- **Terraform:** Generate `main.tf` in a `./terraform` folder.
  - Enforce `region = "us-central1"` for Free Tier.
  - Set `max_instance_count = 1` and `min_instance_count = 0` (Scale-to-Zero).

## 4. Execution
1. Run `gcloud builds submit --tag gcr.io/[PROJECT_ID]/streamlit-app:latest .`
2. Run `terraform init` and `terraform apply -auto-approve`.