# Replaces the ad-hoc `kubectl apply -f /tmp/ingestion-job.yaml` block
# that used to be assembled inline inside .github/workflows/deploy-to-gke.yml
# -- same one-shot-to-completion semantics (data_ingestion/ingestion_pipeline.py
# is unchanged), now declarative and environment-scoped instead of hand-built
# YAML in a workflow file. CD executes it via `gcloud run jobs execute --wait`
# before deploying the app Service, same ordering as the old K8s Job.
resource "google_cloud_run_v2_job" "ingestion" {
  project  = var.project_id
  name     = "${var.app_name}-${var.environment}-ingestion"
  location = var.region
  # See cloud-run-service's identical setting for why.
  deletion_protection = false

  template {
    template {
      service_account = var.service_account_email
      timeout         = "${var.task_timeout_seconds}s"
      max_retries     = 1

      dynamic "vpc_access" {
        for_each = var.vpc_connector_id != null ? [1] : []
        content {
          connector = var.vpc_connector_id
          egress    = "PRIVATE_RANGES_ONLY"
        }
      }

      containers {
        image   = var.image
        command = ["python", "-m", "data_ingestion.ingestion_pipeline"]

        resources {
          limits = {
            cpu    = var.cpu_limit
            memory = var.memory_limit
          }
        }

        dynamic "env" {
          for_each = var.env_vars
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = var.secret_env_vars
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }
}
