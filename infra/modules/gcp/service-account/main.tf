resource "google_service_account" "this" {
  project      = var.project_id
  account_id   = var.account_id
  display_name = var.display_name
}

resource "google_project_iam_member" "roles" {
  for_each = toset(var.project_roles)

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.this.email}"
}

# WIF binding: lets a GitHub Actions run impersonate this SA without a
# long-lived key. Scoped either to "any ref in this repo" (github_ref
# unset -- the builder SA's case) or to exactly one ref (github_ref set --
# every deployer SA's case, so a develop-branch pipeline run can never
# mint a token usable to deploy prod).
resource "google_service_account_iam_member" "wif_binding" {
  count = var.enable_wif_binding ? 1 : 0

  service_account_id = google_service_account.this.name
  role               = "roles/iam.workloadIdentityUser"
  member = var.github_ref != null ? (
    "principalSet://iam.googleapis.com/${var.wif_pool_name}/attribute.ref/${var.github_ref}"
    ) : (
    "principalSet://iam.googleapis.com/${var.wif_pool_name}/attribute.repository/${var.github_repository}"
  )
}
