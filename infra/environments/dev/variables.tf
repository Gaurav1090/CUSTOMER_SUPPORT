variable "cloud_provider" {
  description = <<-EOT
    Which cloud this environment deploys to. Only "gcp" is implemented
    today (infra/providers/gcp). To add another cloud:
      1. implement infra/modules/<cloud>/*
      2. implement infra/providers/<cloud>/main.tf composing them
      3. relax the validation below to allow "<cloud>"
      4. add a sibling module "app_<cloud>" block below, count-gated on
         var.cloud_provider == "<cloud>"
    See infra/modules/aws/README.md and infra/modules/azure/README.md for
    the intended primitive mapping.
  EOT
  type        = string
  default     = "gcp"

  validation {
    condition     = var.cloud_provider == "gcp"
    error_message = "Only \"gcp\" is implemented today. See infra/modules/{aws,azure} for the extension points."
  }
}

variable "gcp_project_id" {
  type = string
}

variable "gcp_region" {
  type    = string
  default = "us-west1"
}

variable "app_name" {
  type    = string
  default = "customer-support-rag"
}

variable "github_repository" {
  type    = string
  default = "Gaurav1090/CUSTOMER_SUPPORT"
}

variable "github_ref" {
  description = "Branch this environment deploys from -- scopes this environment's deployer SA WIF binding."
  type        = string
  default     = "refs/heads/develop"
}

variable "image" {
  description = "Initial placeholder image; CD overwrites this after the first apply."
  type        = string
  default     = "gcr.io/google-samples/hello-app:1.0"
}

variable "min_instance_count" {
  description = "0 = scale to zero when idle -- dev traffic is sporadic, cold starts are an acceptable trade-off for cost here."
  type        = number
  default     = 0
}

variable "max_instance_count" {
  type    = number
  default = 2
}

variable "allowed_origins" {
  type    = string
  default = "http://localhost:8001,http://127.0.0.1:8001"
}
