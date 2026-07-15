variable "gcp_project_id" {
  description = "Single shared project today (project-0fbdbc8d-9379-4cfb-84a) -- dev/test/prod all point at it via their own tfvars for now. Moving an environment to its own project later is a tfvars change in that environment's directory, not a change here."
  type        = string
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
