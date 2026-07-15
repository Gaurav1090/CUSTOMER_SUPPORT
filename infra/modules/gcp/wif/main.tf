# One shared pool/provider, scoped to the repository only. Per-environment
# branch restriction (develop/staging/main) is NOT enforced here -- it
# belongs on each deployer service account's WIF IAM binding instead (see
# infra/modules/gcp/service-account), so a compromised dev-environment
# token can never be replayed to deploy prod. Restricting branch at the
# pool/provider level would require one pool per environment, which is
# more moving parts for no extra safety once bindings are branch-scoped.
resource "google_iam_workload_identity_pool" "github_pool" {
  project                   = var.project_id
  workload_identity_pool_id = var.pool_id
  display_name              = "GitHub Actions WIF Pool"
}

resource "google_iam_workload_identity_pool_provider" "github_provider" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
  workload_identity_pool_provider_id = var.provider_id
  display_name                       = "GitHub Actions WIF Provider"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "attribute.repository == '${var.github_repository}'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}
