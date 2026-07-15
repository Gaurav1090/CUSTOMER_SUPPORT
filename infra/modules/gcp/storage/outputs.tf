output "bucket_name" {
  value = google_storage_bucket.ingestion.name
}

output "landing_path" {
  description = "Value to set LANDING_PATH to on the ingestion Job."
  value       = "gs://${google_storage_bucket.ingestion.name}/landing"
}

output "index_path" {
  description = "Value to set INDEX_PATH to on the ingestion Job and the app Service (both need to read the same BM25 index)."
  value       = "gs://${google_storage_bucket.ingestion.name}/landing/_index"
}
