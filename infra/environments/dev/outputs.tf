output "cloud_run_service_url" {
  value = module.app.service_url
}

output "cloud_run_job_name" {
  value = module.app.job_name
}

output "cicd_deployer_sa_email" {
  value = module.app.deployer_sa_email
}

output "redis_url" {
  value     = module.app.redis_url
  sensitive = true
}
