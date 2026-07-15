variable "project_id" {
  type = string
}

variable "account_id" {
  description = "Service account ID (becomes <account_id>@<project>.iam.gserviceaccount.com)."
  type        = string
}

variable "display_name" {
  type = string
}

variable "project_roles" {
  description = "Project-level IAM roles granted to this service account."
  type        = list(string)
  default     = []
}

variable "wif_pool_name" {
  description = "Full WIF pool resource name (infra/modules/gcp/wif's pool_name output). Leave null to skip WIF binding entirely (not every SA needs to be impersonable from CI -- runtime SAs are attached directly to Cloud Run, never impersonated)."
  type        = string
  default     = null
}

variable "github_repository" {
  description = "owner/repo allowed to impersonate this SA via WIF."
  type        = string
  default     = null
}

variable "github_ref" {
  description = "Restrict WIF impersonation to a single ref, e.g. refs/heads/develop. Null = allow any ref in the repository (used for the shared builder SA, which every environment's pipeline needs). Set for deployer SAs so a dev-branch token can never be replayed to deploy prod."
  type        = string
  default     = null
}
