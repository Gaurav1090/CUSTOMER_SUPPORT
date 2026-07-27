variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "app_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "image" {
  description = "Full image reference, e.g. us-west1-docker.pkg.dev/<project>/<repo>/customer-support-rag:<sha>. CD overwrites this on every deploy via `gcloud run deploy --image`; see the lifecycle.ignore_changes block below for why a later `terraform apply` doesn't revert it."
  type        = string
}

variable "container_port" {
  description = "Port the container actually listens on -- matches the Dockerfile's hardcoded `--port 8001` CMD flag, not Cloud Run's injected $PORT (which the container never reads)."
  type        = number
  default     = 8001
}

variable "service_account_email" {
  type = string
}

variable "min_instance_count" {
  type = number
}

variable "max_instance_count" {
  type = number
}

variable "cpu_limit" {
  type    = string
  default = "2"
}

variable "memory_limit" {
  type    = string
  default = "2Gi"
}

variable "env_vars" {
  description = "Non-secret environment variables, e.g. ALLOWED_ORIGINS, CHROMA_STORAGE_MODE, LANDING_PATH/INDEX_PATH."
  type        = map(string)
  default     = {}
}

variable "secret_env_vars" {
  description = "Map of container env var name -> Secret Manager secret_id (already fully-qualified, e.g. from infra/modules/gcp/secrets' secret_ids output), always bound to the \"latest\" version."
  type        = map(string)
  default     = {}
}

variable "vpc_connector_id" {
  description = "From infra/modules/gcp/networking's connector_id output. Null (the default -- no Redis/private resource in use) means no VPC egress is configured, matching Cloud Run's no-VPC-by-default behavior."
  type        = string
  default     = null
}

variable "allow_unauthenticated" {
  description = "Grant roles/run.invoker to allUsers. The app already gates real access at the HTTP layer via APP_API_KEY (main.py's auth middleware) -- there is no stricter posture in the prior GKE setup to preserve, since that Service was ClusterIP-only with no Ingress at all. Set false and wire up IAP/a load balancer for prod hardening later; not required for parity with what existed before."
  type        = bool
  default     = true
}
