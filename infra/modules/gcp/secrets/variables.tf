variable "project_id" {
  type = string
}

variable "app_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "secret_keys" {
  description = "Logical secret names, e.g. [\"app-api-key\", \"groq-api-key\"]. Values are never set here -- populate with `gcloud secrets versions add <name> --data-file=-` out of band, after apply."
  type        = list(string)
  default = [
    "app-api-key",
    "groq-api-key",
    "chroma-api-key",
    "chroma-tenant",
    "chroma-database",
    "cohere-api-key",
    "langfuse-public-key",
    "langfuse-secret-key",
  ]
}

variable "accessor_service_account_email" {
  description = "Service account granted secretAccessor on every secret this module creates -- normally the environment's Cloud Run runtime SA."
  type        = string
}
