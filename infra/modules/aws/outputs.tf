# Same output names as infra/modules/gcp's composed provider surface
# (see infra/providers/gcp/outputs.tf), all null until real resources
# exist -- keeps infra/environments/*/outputs.tf callable regardless of
# which provider is selected, even though only "gcp" works today.

output "service_url" {
  value = null
}

output "job_name" {
  value = null
}

output "deployer_sa_email" {
  value = null
}

output "runtime_sa_email" {
  value = null
}
