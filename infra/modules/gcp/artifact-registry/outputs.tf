output "repository_name" {
  value = google_artifact_registry_repository.app_repo.name
}

output "repository_id" {
  value = google_artifact_registry_repository.app_repo.repository_id
}

output "repository_url" {
  description = "The docker host/path prefix images are pushed to, e.g. us-west1-docker.pkg.dev/<project>/<repo>."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app_repo.repository_id}"
}
