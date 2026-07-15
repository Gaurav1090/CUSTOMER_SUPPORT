# AWS — not implemented

This module is a typed interface stub, not a working deployment target. It exists so
`infra/environments/*/variables.tf`'s `cloud_provider` parameter has a real place to
point once AWS support is built, without a redesign of the environment/provider layer.

## Intended primitive mapping (GCP → AWS)

| GCP (implemented, `infra/modules/gcp/`) | AWS equivalent |
|---|---|
| Cloud Run Service (`cloud-run-service`) | ECS Fargate service (or App Runner, for a closer serverless match) |
| Cloud Run Job (`cloud-run-job`) | ECS Fargate scheduled/one-off task (`RunTask`) |
| Artifact Registry (`artifact-registry`) | ECR repository |
| Workload Identity Federation (`wif`) | IAM OIDC identity provider for `token.actions.githubusercontent.com` |
| Secret Manager secret containers (`secrets`) | AWS Secrets Manager secrets |
| GCS ingestion bucket (`storage`) | S3 bucket |
| Serverless VPC Access connector (`networking`) | VPC + private subnets + security group, Fargate tasks placed directly in them (no connector concept needed on AWS) |

## Adding real AWS support later

1. Implement the resources above under `infra/modules/aws/` (split into
   sub-modules mirroring `infra/modules/gcp/`'s layout, or keep flat —
   AWS's simpler IAM-per-resource model may not need as many small modules).
2. Implement `infra/providers/aws/main.tf` composing them, matching this
   stub's `variables.tf`/`outputs.tf` contract exactly so callers don't change.
3. Relax the `cloud_provider` validation in each `infra/environments/*/variables.tf`
   to allow `"aws"`.
4. Add a sibling `module "app_aws"` block (guarded by
   `count = var.cloud_provider == "aws" ? 1 : 0`) alongside the existing
   `module "app"` call in each environment.
5. Add the AWS equivalent of `.github/actions/gcp-auth`/`gcp-build-push`
   (`aws-auth`/`aws-build-push`) and extend `_reusable-deploy.yml`'s
   `cloud_provider` branch to call them instead of failing fast.
