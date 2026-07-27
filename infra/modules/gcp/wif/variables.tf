variable "project_id" {
  type = string
}

variable "github_repository" {
  description = "owner/repo that's allowed to mint tokens against this pool, e.g. Gaurav1090/CUSTOMER_SUPPORT."
  type        = string
}

variable "pool_id" {
  type    = string
  default = "github-actions-pool"
}

variable "provider_id" {
  type    = string
  default = "github-actions-provider"
}
