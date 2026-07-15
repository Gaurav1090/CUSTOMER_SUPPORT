output "artifact_registry_repository_id" {
  value = module.artifact_registry.repository_id
}

output "artifact_registry_url" {
  value = module.artifact_registry.repository_url
}

output "wif_pool_name" {
  value = module.wif.pool_name
}

output "wif_provider_name" {
  value = module.wif.provider_name
}

output "builder_sa_email" {
  value = module.builder_service_account.email
}
