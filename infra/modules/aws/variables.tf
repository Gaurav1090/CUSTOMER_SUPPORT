# Mirrors infra/providers/gcp's input surface so infra/environments/* can
# call either provider composition with the same variable names. No
# resources are created from these -- see README.md.

variable "account_id" {
  description = "AWS account ID (GCP equivalent: project_id)."
  type        = string
  default     = null
}

variable "region" {
  type    = string
  default = null
}

variable "app_name" {
  type    = string
  default = null
}

variable "environment" {
  type    = string
  default = null
}

variable "image" {
  type    = string
  default = null
}

variable "min_instance_count" {
  type    = number
  default = null
}

variable "max_instance_count" {
  type    = number
  default = null
}

variable "secret_keys" {
  type    = list(string)
  default = []
}

variable "github_repository" {
  type    = string
  default = null
}
