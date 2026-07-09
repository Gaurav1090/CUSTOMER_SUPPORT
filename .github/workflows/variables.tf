variable "gcp_project_id" {
  description = "The GCP project ID where resources will be deployed."
  type        = string
}

variable "gcp_region" {
  description = "The GCP region for regional resources."
  type        = string
  default     = "us-west1"
}

variable "gcp_zone" {
  description = "The GCP zone for zonal resources."
  type        = string
  default     = "us-west1-a"
}

variable "app_name" {
  description = "The base name for all resources."
  type        = string
  default     = "customer-support-rag"
}

variable "container_port" {
  description = "The port the application container listens on."
  type        = number
  default     = 8001
}

variable "initial_container_image" {
  description = "A placeholder or initial container image for the first deployment. The CI/CD pipeline will update this."
  type        = string
  default     = "gcr.io/google-samples/hello-app:1.0"
}

variable "min_replicas" {
  description = "Minimum number of instances for the managed instance group."
  type        = number
  default     = 1
}