output "enabled_services" {
  description = "The service APIs enabled by this module, used elsewhere as a depends_on target."
  value       = [for service in google_project_service.required_services : service.service]
}
