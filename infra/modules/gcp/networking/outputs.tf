output "connector_id" {
  description = "Null when enable_vpc_connector = false -- infra/modules/gcp/cloud-run-service treats a null connector_id as 'no VPC egress configured'."
  value       = var.enable_vpc_connector ? google_vpc_access_connector.connector[0].id : null
}

output "redis_url" {
  description = "redis://host:port for the Memorystore instance, null when enable_vpc_connector = false. Populate the REDIS_URL secret with this value after apply -- see infra/README.md."
  value       = var.enable_vpc_connector ? "redis://${google_redis_instance.cache[0].host}:${google_redis_instance.cache[0].port}" : null
}
