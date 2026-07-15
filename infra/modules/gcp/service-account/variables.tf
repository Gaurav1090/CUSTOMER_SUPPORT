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

variable "enable_wif_binding" {
  description = "Whether this SA should be impersonable from CI via WIF -- a static, plan-time decision (true for builder/deployer SAs, false for runtime SAs, which are attached directly to Cloud Run and never impersonated). Deliberately NOT inferred from `wif_pool_name != null`: on a first-ever apply, the WIF pool doesn't exist yet, so its name is unknown at plan time and Terraform can't evaluate a count condition built from it."
  type        = bool
  default     = false
}

variable "wif_pool_name" {
  description = "Full WIF pool resource name (infra/modules/gcp/wif's pool_name output). Only read when enable_wif_binding = true."
  type        = string
  default     = null
}

variable "github_repository" {
  description = "owner/repo allowed to impersonate this SA via WIF."
  type        = string
  default     = null
}

variable "github_ref" {
  description = "Restrict WIF impersonation to a single ref, e.g. refs/heads/developer. Null = allow any ref in the repository (used for the shared builder SA, which every environment's pipeline needs). Set for deployer SAs so a dev-branch token can never be replayed to deploy prod."
  type        = string
  default     = null
}
