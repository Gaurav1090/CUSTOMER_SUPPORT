variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "app_name" {
  description = "Base name for the repository (repo is shared across all environments -- see build-once-promote-everywhere in infra/README.md)."
  type        = string
}
