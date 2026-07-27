variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "app_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "ingestion_service_account_email" {
  description = "SA that needs read/write access to run data_ingestion/ingestion_pipeline.py -- normally the environment's Cloud Run runtime SA (the ingestion Job and the app Service share one runtime SA per environment, see infra/providers/gcp)."
  type        = string
}
