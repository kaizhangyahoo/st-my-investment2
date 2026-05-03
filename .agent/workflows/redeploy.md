---
description: Rebuild, Redeploy to Cloud Run, and Clean up old images.
---

0. **Verification**: Ensure the registry and permissions are intact.
   ```bash
   # Check if repository exists
   gcloud artifacts repositories describe streamlit-repo --location=us-central1 || \
   gcloud artifacts repositories create streamlit-repo --repository-format=docker --location=us-central1 --description="Docker repository for Streamlit app"

   # Check and grant Artifact Registry Writer role to the compute service account if missing
   PROJECT_ID=$(gcloud config get-value project)
   PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
   gcloud projects add-iam-policy-binding $PROJECT_ID \
     --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
     --role="roles/artifactregistry.writer"
   ```

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