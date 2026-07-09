terraform {
  # This configures Terraform to store its state file remotely in a GCS bucket.
  # This is a best practice for team collaboration and running Terraform in CI/CD.
  backend "gcs" {
    bucket  = "terraform_customer_rag" # This bucket must be created manually before running 'terraform init'
    prefix  = "prod/customer-support-rag"
  }
}