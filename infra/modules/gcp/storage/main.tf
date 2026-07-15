# Cloud Run Jobs have no persistent disk across executions, unlike the
# local-folder LANDING_PATH/INDEX_PATH default in config/config.yaml --
# this bucket is what LANDING_PATH/INDEX_PATH must point at
# (gs://<this bucket>/landing, gs://<this bucket>/landing/_index) for
# ingestion to work at all once it's running as a Cloud Run Job.
#
# Bucket name includes the project ID since GCS bucket names are globally
# unique (not just unique within this project) -- project_id alone
# already guarantees that, so app_name is deliberately omitted here to
# stay under GCS's 63-char single-component name limit. Including
# app_name pushed this to 65-66 chars and every apply failed with
# "Use of this bucket name is restricted" (GCS's generic error for a
# name that fails validation, length included).
resource "google_storage_bucket" "ingestion" {
  project                     = var.project_id
  name                        = "${var.environment}-ingestion-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }
}

resource "google_storage_bucket_iam_member" "ingestion_access" {
  bucket = google_storage_bucket.ingestion.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.ingestion_service_account_email}"
}
