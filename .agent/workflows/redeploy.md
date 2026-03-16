---
description: Rebuild, Redeploy to Cloud Run, and Clean up old images.
---

> [!TIP]
> If you have updated `.streamlit/secrets.toml`, you should sync it to GCP first:
> `gcloud secrets versions add STREAMLIT_SECRETS --data-file=".streamlit/secrets.toml"`
v
1. Build and push the new container image with 2 tags, a versioned tag and the latest tag.
   ```bash
   TAG="v$(date +%Y%m%d-%H%M)"
   IMAGE="us-central1-docker.pkg.dev/project-e29b631c-29b0-4dd7-86b/streamlit-repo/streamlit-app"
   gcloud builds submit --tag "$IMAGE:$TAG" --tag "$IMAGE:latest" .
   ```

2. Apply Terraform to update the Cloud Run service. (It will point to the new image digest via the `latest` tag).
   ```bash
   export TF_LOG=INFO
   export TF_LOG_PATH="../terraform.log"
   cd terraform && terraform apply -auto-approve
   ```

3. Clean up old images from the registry (keep last 2).
   ```bash
   python3 .agent/scripts/cleanup_registry.py
   ```