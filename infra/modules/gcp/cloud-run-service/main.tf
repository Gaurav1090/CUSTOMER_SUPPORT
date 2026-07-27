resource "google_cloud_run_v2_service" "app" {
  project  = var.project_id
  name     = "${var.app_name}-${var.environment}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  # The provider defaults this to true, which blocks even a legitimate
  # destroy-and-replace (e.g. of a tainted revision) without a manual
  # apply first. Terraform is the sole owner of this resource via CI/CD,
  # so that protection isn't adding safety here, just friction.
  deletion_protection = false

  template {
    service_account = var.service_account_email

    scaling {
      min_instance_count = var.min_instance_count
      max_instance_count = var.max_instance_count
    }

    dynamic "vpc_access" {
      for_each = var.vpc_connector_id != null ? [1] : []
      content {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }
    }

    containers {
      image = var.image

      ports {
        container_port = var.container_port
      }

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

      # Mirrors deploy/k8s.yaml's readinessProbe -- both hit /ready,
      # startup_probe is Cloud Run's equivalent gate before traffic is
      # routed to a new revision.
      startup_probe {
        http_get {
          path = "/ready"
          port = var.container_port
        }
        initial_delay_seconds = 20
        period_seconds        = 10
        timeout_seconds       = 5
        failure_threshold     = 3
      }

      # Mirrors deploy/k8s.yaml's livenessProbe -- both hit /health.
      liveness_probe {
        http_get {
          path = "/health"
          port = var.container_port
        }
        initial_delay_seconds = 30
        period_seconds        = 30
        timeout_seconds       = 5
        failure_threshold     = 3
      }
    }
  }

  # CD deploys a new image via `gcloud run deploy --image=...` between
  # Terraform applies. Without this, the next `terraform apply` would
  # revert the running revision back to whatever image is in this file.
  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
