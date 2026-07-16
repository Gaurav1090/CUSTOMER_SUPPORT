locals {
  # google_vpc_access_connector names are capped at 25 chars
  # (^[a-z][-a-z0-9]{0,23}[a-z0-9]$) -- far tighter than every other
  # resource name in this module (e.g. the 30-char service-account limit),
  # and app_name alone ("customer-support-rag") already eats 20 of those.
  # Hash-suffix a short fixed prefix instead of reusing app_name so this
  # doesn't silently break again if app_name ever changes.
  connector_name = "vpc-${var.environment}-${substr(md5(var.app_name), 0, 6)}"
}

resource "google_vpc_access_connector" "connector" {
  count = var.enable_vpc_connector ? 1 : 0

  project       = var.project_id
  name          = local.connector_name
  region        = var.region
  network       = var.network
  ip_cidr_range = var.connector_cidr
  # Provider no longer defaults this silently -- creation fails with
  # "must specify either max_throughput or max_instances" without it.
  # 2/3 e2-micro instances is Serverless VPC Access's own historical
  # default range, kept explicit here instead.
  min_instances = 2
  max_instances = 3
}

# Memorystore requires a Private Services Access VPC peering to the target
# network -- this reserves the IP range for that peering and creates the
# peering connection. Only needed (and only created) when a Memorystore
# instance actually exists, i.e. same gate as the connector above.
resource "google_compute_global_address" "private_service_range" {
  count = var.enable_vpc_connector ? 1 : 0

  project       = var.project_id
  name          = "${var.app_name}-${var.environment}-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = "projects/${var.project_id}/global/networks/${var.network}"
}

resource "google_service_networking_connection" "private_service_connection" {
  count = var.enable_vpc_connector ? 1 : 0

  network                 = "projects/${var.project_id}/global/networks/${var.network}"
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_range[0].name]
}

# Basic tier (no HA/replica) -- this is a demo/dev cache+session store, not
# a durable data store; the app already degrades gracefully to in-memory
# fallback if Redis is ever unreachable (see utils/ops.py's
# _build_redis_client), so paying for Standard-tier HA isn't justified
# here. Reassess if this instance starts backing anything that needs to
# survive a zone failure.
resource "google_redis_instance" "cache" {
  count = var.enable_vpc_connector ? 1 : 0

  project             = var.project_id
  name                = "${var.app_name}-${var.environment}-redis"
  region              = var.region
  tier                = "BASIC"
  memory_size_gb      = 1
  redis_version       = "REDIS_7_0"
  authorized_network  = "projects/${var.project_id}/global/networks/${var.network}"
  connect_mode        = "PRIVATE_SERVICE_ACCESS"

  depends_on = [google_service_networking_connection.private_service_connection]
}
