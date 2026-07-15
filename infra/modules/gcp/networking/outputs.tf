output "connector_id" {
  description = "Null when enable_vpc_connector = false -- infra/modules/gcp/cloud-run-service treats a null connector_id as 'no VPC egress configured'."
  value       = var.enable_vpc_connector ? google_vpc_access_connector.connector[0].id : null
}
