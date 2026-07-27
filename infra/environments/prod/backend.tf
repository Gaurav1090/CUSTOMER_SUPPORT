terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  # Prefix matches the original (pre-migration) backend.tf exactly, so
  # prod's Terraform state history continues rather than starting fresh.
  backend "gcs" {
    bucket = "terraform_customer_rag"
    prefix = "prod/customer-support-rag"
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}
