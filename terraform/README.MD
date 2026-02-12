# Streamlit Portfolio Dashboard

This project is a Streamlit-based Portfolio Management Dashboard deployed to Google Cloud Run.

## Project Details
- **Project ID**: `project-e29b631c-29b0-4dd7-86b`
- **Region**: `us-central1`
- **Live URL**: [https://streamlit-app-rj6qghjncq-uc.a.run.app](https://streamlit-app-rj6qghjncq-uc.a.run.app)

---

## 🚀 How to Redeploy Manual

If you have made code changes and want to update the live application:

1. **Build and Push the Container**:
   We recommend pushing with both a unique version tag (based on timestamp) and the `latest` tag:
   ```bash
   TAG="v$(date +%Y%m%d-%H%M)"
   IMAGE="us-central1-docker.pkg.dev/project-e29b631c-29b0-4dd7-86b/streamlit-repo/streamlit-app"
   gcloud builds submit --tag "$IMAGE:$TAG" --tag "$IMAGE:latest" .
   ```

2. **Deploy via Terraform**:
   Navigate to the terraform directory and apply (this will point Cloud Run to the new image):
   ```bash
   cd terraform
   terraform apply -auto-approve
   ```

---

## ⏪ How to Rollback

If you need to revert to a previous version of the application:

### Option 1: Quick Rollback via GCP Console
1. Go to **Cloud Run** in the GCP Console.
2. Click on the `streamlit-app` service.
3. Select the **Revisions** tab.
4. Click **Manage Traffic** and assign 100% of traffic to a previous stable revision.

### Option 2: Rollback via Terraform (Permanent)
1. Open `terraform/main.tf`.
2. Find the versioned tag you want to revert to in the Artifact Registry (e.g., `v20240123-1000`).
3. Temporarily update the `image` field:
   ```hcl
   image = "us-central1-docker.pkg.dev/project-e29b631c-29b0-4dd7-86b/streamlit-repo/streamlit-app:v20240123-1000"
   ```
4. Run `terraform apply -auto-approve`.
5. Don't forget to change it back to `:latest` once you've fixed the issue in the main branch!

---

## 🧹 How to Delete and Clear Resources

To shut down the application and delete all GCP resources (Cloud Run service, IAM bindings, etc.):

1. **Destroy Infrastructure**:
   Navigate to the terraform directory:
   ```bash
   cd terraform
   terraform destroy -auto-approve
   ```

> [!NOTE]
> This will remove the Cloud Run service but will NOT delete the Artifact Registry repository or the stored images by default (to prevent data loss of images). You can manually delete the repository via `gcloud artifacts repositories delete streamlit-repo --location=us-central1`.

---

## 🛠️ How to Start From Scratch

If you have deleted the resources or are starting in a fresh environment:

1. **Auth & Project Setup**:
   ```bash
   gcloud auth login
   gcloud config set project project-e29b631c-29b0-4dd7-86b
   ```

2. **Prepare Repository (If deleted)**:
   ```bash
   gcloud artifacts repositories create streamlit-repo --repository-format=docker --location=us-central1
   ```

3. **Build and Push**:
   ```bash
   gcloud builds submit --tag us-central1-docker.pkg.dev/project-e29b631c-29b0-4dd7-86b/streamlit-repo/streamlit-app:latest .
   ```

4. **Terraform Initialize & Apply**:
   ```bash
   cd terraform
   terraform init
   terraform apply -auto-approve
   ```

---

## 📄 License
The Terraform version used is **1.5.7** (Mozilla Public License v2.0).
