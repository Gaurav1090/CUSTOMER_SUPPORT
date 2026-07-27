# Azure — not implemented

This module is a typed interface stub, not a working deployment target. It exists so
`infra/environments/*/variables.tf`'s `cloud_provider` parameter has a real place to
point once Azure support is built, without a redesign of the environment/provider layer.

## Intended primitive mapping (GCP → Azure)

| GCP (implemented, `infra/modules/gcp/`) | Azure equivalent |
|---|---|
| Cloud Run Service (`cloud-run-service`) | Container Apps (a Container App, `Microsoft.App/containerApps`) |
| Cloud Run Job (`cloud-run-job`) | Container Apps Job (`Microsoft.App/jobs`, trigger type `Manual`) |
| Artifact Registry (`artifact-registry`) | Azure Container Registry (ACR) |
| Workload Identity Federation (`wif`) | Azure AD Workload Identity Federation (federated credential on an App Registration / user-assigned managed identity, trusting `token.actions.githubusercontent.com`) |
| Secret Manager secret containers (`secrets`) | Azure Key Vault secrets |
| GCS ingestion bucket (`storage`) | Azure Blob Storage container |
| Serverless VPC Access connector (`networking`) | VNet integration on the Container Apps environment (built into the Container Apps environment resource, no separate connector resource needed) |

## Adding real Azure support later

1. Implement the resources above under `infra/modules/azure/` (split into
   sub-modules mirroring `infra/modules/gcp/`'s layout, or keep flat).
2. Implement `infra/providers/azure/main.tf` composing them, matching this
   stub's `variables.tf`/`outputs.tf` contract exactly so callers don't change.
3. Relax the `cloud_provider` validation in each `infra/environments/*/variables.tf`
   to allow `"azure"`.
4. Add a sibling `module "app_azure"` block (guarded by
   `count = var.cloud_provider == "azure" ? 1 : 0`) alongside the existing
   `module "app"` call in each environment.
5. Add the Azure equivalent of `.github/actions/gcp-auth`/`gcp-build-push`
   (`azure-auth`/`azure-build-push`) and extend `_reusable-deploy.yml`'s
   `cloud_provider` branch to call them instead of failing fast.
