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

variable "enable_vpc_connector" {
  description = "Cloud Run fully-managed has no VPC by default and needs none of the old GKE setup's Cloud Router/NAT (those existed only for GKE private-node egress, and were torn down along with the GKE cluster). Set true only when a private resource -- e.g. a reprovisioned Memorystore Redis instance -- needs to be reached from Cloud Run. No Redis instance exists as of this module's introduction, so this defaults off and creates nothing."
  type        = bool
  default     = false
}

variable "network" {
  description = "VPC network name the connector attaches to, only used when enable_vpc_connector = true."
  type        = string
  default     = "default"
}

variable "connector_cidr" {
  description = "/28 CIDR range for the connector, only used when enable_vpc_connector = true. Must not overlap any existing subnet."
  type        = string
  default     = "10.8.0.0/28"
}
