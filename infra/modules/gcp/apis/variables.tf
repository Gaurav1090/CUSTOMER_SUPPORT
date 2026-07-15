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
    # Not used yet (no Redis instance exists after the 2026-07 cleanup) --
    # kept enabled so re-provisioning Memorystore later needs no API
    # activation step, only new resources in infra/modules/gcp/networking.
    "redis.googleapis.com",
  ]
}
