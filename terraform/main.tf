provider "google" {
  project = "project-e29b631c-29b0-4dd7-86b"
  region  = "us-central1"
}

resource "google_cloud_run_v2_service" "streamlit_app" {
  name     = "streamlit-app"
  location = "us-central1"
  ingress  = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false  # allow terraform destroy. Set to true to prevent accidental deletion

  template {
    labels = {
      "deployment_time" = lower(replace(timestamp(), ":", "-"))
    }
    scaling {
      max_instance_count = 1
      min_instance_count = 0
    }
    containers {
      image = "us-central1-docker.pkg.dev/project-e29b631c-29b0-4dd7-86b/streamlit-repo/streamlit-app:latest"
      ports {
        container_port = 8080
      }
      
      env {
        name = "FIREBASE_SERVICE_ACCOUNT"
        value_source {
          secret_key_ref {
            secret  = "FIREBASE_SERVICE_ACCOUNT"
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "streamlit-secrets"
        mount_path = "/usr/src/app/.streamlit"
      }
    }

    volumes {
      name = "streamlit-secrets"
      secret {
        secret = "STREAMLIT_SECRETS"
        items {
          version = "latest"
          path    = "secrets.toml"
        }
      }
    }
  }
}

# Grant the Cloud Run service account access to the secrets
# Default Compute Service Account
data "google_project" "project" {}

resource "google_secret_manager_secret_iam_member" "streamlit_secrets_access" {
  secret_id = "STREAMLIT_SECRETS"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

resource "google_secret_manager_secret_iam_member" "firebase_secrets_access" {
  secret_id = "FIREBASE_SERVICE_ACCOUNT"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

resource "google_cloud_run_v2_service_iam_member" "noauth" {
  location = google_cloud_run_v2_service.streamlit_app.location
  name     = google_cloud_run_v2_service.streamlit_app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "url" {
  value = google_cloud_run_v2_service.streamlit_app.uri
}
