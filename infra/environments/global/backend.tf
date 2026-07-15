terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  backend "gcs" {
    bucket = "terraform_customer_rag"
    prefix = "global/customer-support-rag"
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}
