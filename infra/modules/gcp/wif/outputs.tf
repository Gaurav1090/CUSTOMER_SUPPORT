output "pool_id" {
  value = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
}

output "pool_name" {
  value = google_iam_workload_identity_pool.github_pool.name
}

output "provider_id" {
  value = google_iam_workload_identity_pool_provider.github_provider.workload_identity_pool_provider_id
}

output "provider_name" {
  description = "Full resource name, used as the workload_identity_provider input to google-github-actions/auth."
  value       = google_iam_workload_identity_pool_provider.github_provider.name
}
