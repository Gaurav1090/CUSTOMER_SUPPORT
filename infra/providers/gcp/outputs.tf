output "service_url" {
  value = module.cloud_run_service.url
}

output "job_name" {
  value = module.cloud_run_job.job_name
}

output "deployer_sa_email" {
  value = module.deployer_service_account.email
}

output "runtime_sa_email" {
  value = module.runtime_service_account.email
}

output "redis_url" {
  description = "redis://host:port for Memorystore, null when enable_vpc_connector = false. Use this to populate the REDIS_URL secret after apply -- see infra/README.md."
  value       = module.networking.redis_url
  sensitive   = true
}
