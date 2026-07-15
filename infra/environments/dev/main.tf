data "terraform_remote_state" "global" {
  backend = "gcs"
  config = {
    bucket = "terraform_customer_rag"
    prefix = "global/customer-support-rag"
  }
}

module "app" {
  source = "../../providers/gcp"

  project_id         = var.gcp_project_id
  region             = var.gcp_region
  app_name           = var.app_name
  environment        = "dev"
  image              = var.image
  min_instance_count = var.min_instance_count
  max_instance_count = var.max_instance_count
  allowed_origins    = var.allowed_origins

  github_repository = var.github_repository
  github_ref        = var.github_ref

  wif_pool_name                   = data.terraform_remote_state.global.outputs.wif_pool_name
  artifact_registry_repository_id = data.terraform_remote_state.global.outputs.artifact_registry_repository_id
}
