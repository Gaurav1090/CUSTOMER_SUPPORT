# Cloud Run Jobs have no persistent disk across executions, unlike the
# local-folder LANDING_PATH/INDEX_PATH default in config/config.yaml --
# this bucket is what LANDING_PATH/INDEX_PATH must point at
# (gs://<this bucket>/landing, gs://<this bucket>/landing/_index) for
# ingestion to work at all once it's running as a Cloud Run Job. Bucket
# name includes the project ID since GCS bucket names are globally unique.
resource "google_storage_bucket" "ingestion" {
  project                     = var.project_id
  name                        = "${var.app_name}-${var.environment}-ingestion-${var.project_id}"
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
