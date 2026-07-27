resource "google_artifact_registry_repository" "app_repo" {
  provider      = google
  project       = var.project_id
  location      = var.region
  repository_id = "${var.app_name}-repo"
  description   = "Docker repository for the customer support RAG app -- shared across dev/test/prod, images promoted by SHA tag, never rebuilt per environment."
  format        = "DOCKER"
}
