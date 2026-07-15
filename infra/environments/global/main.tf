module "apis" {
  source     = "../../modules/gcp/apis"
  project_id = var.gcp_project_id
}

module "artifact_registry" {
  source     = "../../modules/gcp/artifact-registry"
  project_id = var.gcp_project_id
  region     = var.gcp_region
  app_name   = var.app_name

  depends_on = [module.apis]
}

module "wif" {
  source            = "../../modules/gcp/wif"
  project_id        = var.gcp_project_id
  github_repository = var.github_repository

  depends_on = [module.apis]
}

# Shared builder SA -- one image build per pipeline run, reused across
# dev/test/prod (build-once-promote-everywhere), so this SA lives at the
# global level rather than being duplicated per environment.
module "builder_service_account" {
  source = "../../modules/gcp/service-account"

  project_id    = var.gcp_project_id
  account_id    = "${var.app_name}-builder"
  display_name  = "CI image builder SA"
  project_roles = ["roles/artifactregistry.writer"]

  wif_pool_name     = module.wif.pool_name
  github_repository = var.github_repository
  # github_ref left null -- any branch's pipeline can build (dev/test/prod
  # all build the same way), only *deploying* is branch-restricted.

  depends_on = [module.wif]
}
