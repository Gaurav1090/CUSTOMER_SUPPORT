output "secret_ids" {
  description = "Map of logical key -> full Secret Manager secret_id, for wiring into cloud-run-service/cloud-run-job env vars."
  value       = { for key, secret in google_secret_manager_secret.this : key => secret.secret_id }
}
