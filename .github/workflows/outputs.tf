output "artifact_registry_repository" {
  description = "The full name of the Artifact Registry repository."
  value       = google_artifact_registry_repository.app_repo.name
}

output "gke_cluster_name" {
  description = "The name of the GKE cluster."
  value       = google_container_cluster.primary.name
}

output "cicd_service_account_email" {
  description = "The email of the service account for the CI/CD pipeline."
  value       = google_service_account.cicd_sa.email
  sensitive   = true
}

output "workload_identity_pool" {
  description = "The name of the Workload Identity Pool for GitHub Actions."
  value       = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
}

output "workload_identity_provider" {
  description = "The name of the Workload Identity Provider for GitHub Actions."
  value       = google_iam_workload_identity_pool_provider.github_provider.workload_identity_pool_provider_id
}