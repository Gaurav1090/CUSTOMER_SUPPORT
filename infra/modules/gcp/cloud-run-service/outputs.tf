output "service_name" {
  value = google_cloud_run_v2_service.app.name
}

output "url" {
  value = google_cloud_run_v2_service.app.uri
}
