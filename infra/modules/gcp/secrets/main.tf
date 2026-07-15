# Secret *containers* only -- no plaintext values ever pass through
# Terraform, so nothing sensitive lands in tfstate or in GitHub Actions
# secrets. Populate actual values after apply:
#   echo -n "$VALUE" | gcloud secrets versions add <app_name>-<environment>-<key> \
#     --project=<project_id> --data-file=-
resource "google_secret_manager_secret" "this" {
  for_each = toset(var.secret_keys)

  project   = var.project_id
  secret_id = "${var.app_name}-${var.environment}-${each.key}"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = google_secret_manager_secret.this

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.accessor_service_account_email}"
}
