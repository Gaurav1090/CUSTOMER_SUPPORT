resource "google_vpc_access_connector" "connector" {
  count = var.enable_vpc_connector ? 1 : 0

  project       = var.project_id
  name          = "${var.app_name}-${var.environment}-connector"
  region        = var.region
  network       = var.network
  ip_cidr_range = var.connector_cidr
}
