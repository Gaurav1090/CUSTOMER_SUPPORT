# Mirrors infra/providers/gcp's variables.tf exactly -- see that file for
# what each input means. Not implemented; see infra/modules/aws/README.md.

variable "account_id" {
  type    = string
  default = null
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

variable "github_repository" {
  type    = string
  default = null
}

variable "github_ref" {
  type    = string
  default = null
}
