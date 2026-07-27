module "app" {
  source = "../../modules/aws"

  account_id         = var.account_id
  region             = var.region
  app_name           = var.app_name
  environment        = var.environment
  image              = var.image
  min_instance_count = var.min_instance_count
  max_instance_count = var.max_instance_count
  github_repository  = var.github_repository
}
