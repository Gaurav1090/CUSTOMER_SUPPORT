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

# roles/storage.objectAdmin is object-scoped only -- it has zero
# bucket-level permissions (storage.buckets.get included). gcsfs's
# makedirs() does a bucket-level existence check before writing, which
# failed with "Bucket does not exist" (GCS's generic error for a 403,
# same not-found-instead-of-denied pattern Secret Manager uses) on the
# first real ingestion run despite the bucket being right there.
resource "google_storage_bucket_iam_member" "ingestion_bucket_reader" {
  bucket = google_storage_bucket.ingestion.name
  role   = "roles/storage.legacyBucketReader"
  member = "serviceAccount:${var.ingestion_service_account_email}"
}
