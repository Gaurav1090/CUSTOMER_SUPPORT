resource "google_project_service" "required_services" {
  for_each = toset(var.services)

  project                    = var.project_id
  service                    = each.key
  disable_dependent_services = true
  disable_on_destroy         = false
}
