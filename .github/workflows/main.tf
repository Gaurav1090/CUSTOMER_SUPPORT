provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

resource "google_project_service" "required_services" {
  for_each = toset([
    "iam.googleapis.com",
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "secretmanager.googleapis.com"
  ])
  service                    = each.key
  disable_dependent_services = true
  disable_on_destroy         = false
}

# 1. Artifact Registry to store Docker images
resource "google_artifact_registry_repository" "app_repo" {
  provider      = google
  location      = var.gcp_region
  repository_id = "${var.app_name}-repo"
  description   = "Docker repository for the customer support RAG app"
  format        = "DOCKER"
  depends_on    = [google_project_service.required_services]
}

# 2. GKE Cluster (Private, Regional, with Workload Identity)
resource "google_container_cluster" "primary" {
  provider               = google
  name                   = "${var.app_name}-cluster"
  location               = var.gcp_region
  initial_node_count     = 1
  deletion_protection    = false # Set to false to allow destruction via Terraform
  remove_default_node_pool = true

  # Enable Workload Identity for secure access to other GCP services
  workload_identity_config {
    workload_pool = "${var.gcp_project_id}.svc.id.goog"
  }

  # Private cluster for enhanced security
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false # Control plane public, nodes private
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }

  ip_allocation_policy {
    # Use VPC-native traffic routing
  }

  depends_on = [google_project_service.required_services]
}

resource "google_container_node_pool" "primary_nodes" {
  provider   = google
  name       = "primary-node-pool"
  location   = var.gcp_region
  cluster    = google_container_cluster.primary.name
  node_count = 1

  autoscaling {
    min_node_count = 1
    max_node_count = 5
  }

  node_config {
    machine_type = "e2-medium"
    disk_size_gb = 40              # was defaulting to 100GB
    disk_type    = "pd-standard"
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }
}

# 3. Service Account for the Application (to be used by Workload Identity)
resource "google_service_account" "app_sa" {
  account_id   = "${var.app_name}-sa"
  display_name = "Service Account for Customer Support RAG App"
}

# Grant the app's service account permission to read secrets
resource "google_project_iam_member" "app_sa_secret_accessor" {
  project = var.gcp_project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.app_sa.email}"
}

# 4. IAM binding to link the Kubernetes Service Account to the Google Service Account
resource "google_service_account_iam_member" "app_sa_workload_identity_user" {
  service_account_id = google_service_account.app_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.gcp_project_id}.svc.id.goog[default/${var.app_name}-ksa]"
  depends_on         = [google_container_cluster.primary]
}

# --- CI/CD Infrastructure for GitHub Actions ---

# 5. Service Account for the CI/CD pipeline
resource "google_service_account" "cicd_sa" {
  account_id   = "${var.app_name}-cicd-sa"
  display_name = "CI/CD Service Account"
}

# Grant the CI/CD SA roles to deploy to GKE and push to Artifact Registry
resource "google_project_iam_member" "cicd_sa_roles" {
  for_each = toset([
    "roles/container.developer",      # To deploy to GKE
    "roles/artifactregistry.writer",  # To push images to GAR
  ])
  project = var.gcp_project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.cicd_sa.email}"
}

# 6. Workload Identity Federation for GitHub Actions
resource "google_iam_workload_identity_pool" "github_pool" {
  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions WIF Pool"
}

resource "google_iam_workload_identity_pool_provider" "github_provider" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions-provider"
  display_name                       = "GitHub Actions WIF Provider"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }
  attribute_condition = "attribute.repository == 'Gaurav1090/CUSTOMER_SUPPORT' && assertion.ref == 'refs/heads/main' && (assertion.event_name == 'push' || assertion.event_name == 'workflow_run')"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Allow GitHub Actions from your repo to impersonate the CI/CD SA
resource "google_service_account_iam_member" "cicd_sa_wif_user" {
  service_account_id = google_service_account.cicd_sa.name
  role               = "roles/iam.workloadIdentityUser"
  # Replace with your GitHub org/username and repo name
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_pool.name}/attribute.repository/Gaurav1090/CUSTOMER_SUPPORT"
}

data "google_compute_network" "default" {
  name = "default"
}

resource "google_compute_router" "router" {
  name    = "${var.app_name}-router"
  region  = var.gcp_region
  network = data.google_compute_network.default.id
}

resource "google_compute_router_nat" "nat" {
  name                               = "${var.app_name}-nat"
  router                             = google_compute_router.router.name
  region                             = var.gcp_region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

data "google_project" "current" {
  project_id = var.gcp_project_id
}

resource "google_project_iam_member" "gke_nodes_artifact_registry_reader" {
  project = var.gcp_project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${data.google_project.current.number}-compute@developer.gserviceaccount.com"
}