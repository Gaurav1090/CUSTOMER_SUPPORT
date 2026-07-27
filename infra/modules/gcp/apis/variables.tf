variable "project_id" {
  description = "GCP project ID to enable services in."
  type        = string
}

variable "services" {
  description = "List of service APIs to enable."
  type        = list(string)
  default = [
    "iam.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "secretmanager.googleapis.com",
    "redis.googleapis.com",
    # Needed for the private services VPC peering Memorystore requires
    # (google_service_networking_connection in infra/modules/gcp/networking).
    "servicenetworking.googleapis.com",
    # Needed by google_vpc_access_connector itself -- missed on the first
    # pass, which let the connector resource fail with a 403 SERVICE_DISABLED
    # after the Redis instance had already been created (see the dev apply
    # from this same rollout).
    "vpcaccess.googleapis.com",
  ]
}
