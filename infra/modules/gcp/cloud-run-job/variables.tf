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
  description = "Same image as the app Service (build-once-promote-everywhere) -- overwritten on each deploy via `gcloud run jobs deploy --image`, matching cloud-run-service's ignore_changes handling."
  type        = string
}

variable "service_account_email" {
  type = string
}

variable "env_vars" {
  type    = map(string)
  default = {}
}

variable "secret_env_vars" {
  type    = map(string)
  default = {}
}

variable "vpc_connector_id" {
  type    = string
  default = null
}

variable "cpu_limit" {
  type    = string
  default = "1"
}

variable "memory_limit" {
  type    = string
  default = "1Gi"
}

variable "task_timeout_seconds" {
  description = "Ingestion is usually seconds-to-low-minutes for the bundled demo dataset, but a larger corpus could take longer -- generous default."
  type        = number
  default     = 1800
}
