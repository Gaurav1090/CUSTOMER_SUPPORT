locals {
  # Container env var name -> secret module's logical key. The secrets
  # module namespaces the actual Secret Manager secret_id per environment
  # (${app_name}-${environment}-${logical_key}); this map only translates
  # between the two naming conventions.
  secret_env_var_map = {
    APP_API_KEY         = "app-api-key"
    GROQ_API_KEY        = "groq-api-key"
    CHROMA_API_KEY      = "chroma-api-key"
    CHROMA_TENANT       = "chroma-tenant"
    CHROMA_DATABASE     = "chroma-database"
    COHERE_API_KEY      = "cohere-api-key"
    LANGFUSE_PUBLIC_KEY = "langfuse-public-key"
    LANGFUSE_SECRET_KEY = "langfuse-secret-key"
  }
}

module "runtime_service_account" {
  source = "../../modules/gcp/service-account"

  project_id    = var.project_id
  account_id    = "${var.app_name}-${var.environment}-run"
  display_name  = "Cloud Run runtime SA (${var.environment})"
  project_roles = ["roles/secretmanager.secretAccessor"]
  # No WIF binding -- this SA is attached directly to the Cloud Run
  # Service/Job, never impersonated from CI.
}

module "deployer_service_account" {
  source = "../../modules/gcp/service-account"

  project_id = var.project_id
  # google_service_account.account_id has a 30-char limit -- "-deploy"
  # pushed "customer-support-rag-<env>-deploy" over it (31-32 chars
  # depending on environment). "-cd" keeps every environment's SA name
  # under the limit with room to spare.
  account_id   = "${var.app_name}-${var.environment}-cd"
  display_name = "CI/CD deployer SA (${var.environment})"
  # run.admin: deploy/manage the Cloud Run service and job.
  # iam.serviceAccountUser: attach the runtime SA to them.
  # artifactregistry.reader: pull the built image at deploy time --
  # missing this produced a real failure on the first live deploy attempt
  # ("PERMISSION_DENIED: artifactregistry.repositories.downloadArtifacts").
  project_roles = ["roles/run.admin", "roles/iam.serviceAccountUser", "roles/artifactregistry.reader"]

  enable_wif_binding = true
  wif_pool_name      = var.wif_pool_name
  github_repository  = var.github_repository
  github_ref         = var.github_ref
}

module "secrets" {
  source = "../../modules/gcp/secrets"

  project_id                     = var.project_id
  app_name                       = var.app_name
  environment                    = var.environment
  secret_keys                    = distinct(values(local.secret_env_var_map))
  accessor_service_account_email = module.runtime_service_account.email
}

module "storage" {
  source = "../../modules/gcp/storage"

  project_id                      = var.project_id
  region                          = var.region
  app_name                        = var.app_name
  environment                     = var.environment
  ingestion_service_account_email = module.runtime_service_account.email
}

module "networking" {
  source = "../../modules/gcp/networking"

  project_id           = var.project_id
  region               = var.region
  app_name             = var.app_name
  environment          = var.environment
  enable_vpc_connector = var.enable_vpc_connector
}

module "cloud_run_service" {
  source = "../../modules/gcp/cloud-run-service"

  project_id            = var.project_id
  region                = var.region
  app_name              = var.app_name
  environment           = var.environment
  image                 = var.image
  service_account_email = module.runtime_service_account.email
  min_instance_count    = var.min_instance_count
  max_instance_count    = var.max_instance_count
  vpc_connector_id      = module.networking.connector_id

  env_vars = merge(
    {
      ALLOWED_ORIGINS     = var.allowed_origins
      CHROMA_STORAGE_MODE = "cloud"
      LANDING_PATH        = module.storage.landing_path
      INDEX_PATH          = module.storage.index_path
    },
    var.non_secret_env_vars,
  )

  secret_env_vars = {
    for env_var_name, logical_key in local.secret_env_var_map :
    env_var_name => module.secrets.secret_ids[logical_key]
  }
}

module "cloud_run_job" {
  source = "../../modules/gcp/cloud-run-job"

  project_id            = var.project_id
  region                = var.region
  app_name              = var.app_name
  environment           = var.environment
  image                 = var.image
  service_account_email = module.runtime_service_account.email
  vpc_connector_id      = module.networking.connector_id

  env_vars = merge(
    {
      CHROMA_STORAGE_MODE = "cloud"
      LANDING_PATH        = module.storage.landing_path
      INDEX_PATH          = module.storage.index_path
    },
    var.non_secret_env_vars,
  )

  secret_env_vars = {
    for env_var_name, logical_key in local.secret_env_var_map :
    env_var_name => module.secrets.secret_ids[logical_key]
    if contains(["GROQ_API_KEY", "CHROMA_API_KEY", "CHROMA_TENANT", "CHROMA_DATABASE"], env_var_name)
    # Ingestion only needs Chroma + an LLM key (embeddings run locally,
    # per config/config.yaml's default huggingface provider) -- narrower
    # than the app Service's full secret set on purpose.
  }
}
