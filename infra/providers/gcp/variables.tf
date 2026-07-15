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
  description = "dev | test | prod."
  type        = string
}

variable "image" {
  description = "Initial container image. Overwritten by CD via `gcloud run deploy --image`/`gcloud run jobs deploy --image` after the first apply -- see cloud-run-service/cloud-run-job's lifecycle.ignore_changes."
  type        = string
}

variable "min_instance_count" {
  type = number
}

variable "max_instance_count" {
  type = number
}

variable "github_repository" {
  type = string
}

variable "github_ref" {
  description = "Branch this environment deploys from, e.g. refs/heads/developer -- scopes the deployer SA's WIF binding so this environment's CI token can never be replayed against another environment."
  type        = string
}

# -- Outputs from infra/environments/global, passed in by the caller
# (infra/environments/{dev,test,prod}/main.tf) via a terraform_remote_state
# read, rather than this module reading remote state directly -- keeps
# this module a plain "given these inputs, build environment resources"
# unit with no backend-specific knowledge, which matters once
# infra/providers/aws or azure need the same treatment.
variable "wif_pool_name" {
  type = string
}

variable "artifact_registry_repository_id" {
  type = string
}

variable "non_secret_env_vars" {
  description = "Extra non-secret env vars beyond what this module always sets (ALLOWED_ORIGINS, CHROMA_STORAGE_MODE, LANDING_PATH, INDEX_PATH) -- e.g. LLM_PROVIDER overrides for a given environment."
  type        = map(string)
  default     = {}
}

variable "allowed_origins" {
  type = string
}

variable "enable_vpc_connector" {
  description = "See infra/modules/gcp/networking -- off by default, no Redis instance exists today."
  type        = bool
  default     = false
}
