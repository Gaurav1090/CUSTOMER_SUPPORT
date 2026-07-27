# Infrastructure

Terraform for deploying this app to Cloud Run, across three environments (dev/test/prod),
structured so a second cloud provider can be added later without redesigning this layer.
Replaces the earlier GKE-based setup (deleted 2026-07 — see git history for
`deploy/k8s.yaml` and `.github/workflows/deploy-to-gke.yml` if you need to compare).

## Layout

```
modules/
  gcp/            # real, implemented resources -- one directory per concern
    apis/ artifact-registry/ wif/ service-account/
    cloud-run-service/ cloud-run-job/ secrets/ storage/ networking/
  aws/            # typed interface stub, zero resources -- see aws/README.md
  azure/          # typed interface stub, zero resources -- see azure/README.md
providers/
  gcp/            # composes modules/gcp/* into one "deploy this app" unit
  aws/            # stub composition, mirrors gcp's variable/output names
  azure/          # stub composition, mirrors gcp's variable/output names
environments/
  global/         # project-wide singletons: enabled APIs, the (shared,
                  # build-once-promote-everywhere) Artifact Registry repo,
                  # the WIF pool/provider, and the CI builder SA
  dev/            # deploys from `developer`, calls providers/gcp
  test/           # deploys from `staging`, calls providers/gcp
  prod/           # deploys from `main`, calls providers/gcp
```

Each `environments/*` directory is a separate Terraform root module with its own GCS
state prefix (all sharing the `terraform_customer_rag` bucket, distinct `prefix` per
environment) — a mistake in `dev` can never corrupt `prod`'s state. `global` must be
applied first; `dev`/`test`/`prod` read its outputs via `terraform_remote_state`.

## Why one shared project today

`dev`/`test`/`prod` all point at the same GCP project (`project-0fbdbc8d-9379-4cfb-84a`)
via their own `terraform.tfvars` — that's the only project that currently exists.
Environment isolation still comes from resource naming (`customer-support-rag-dev` etc.),
separate service accounts, separate Terraform state, and branch-scoped WIF bindings (see
below). Moving an environment to its own project later is a one-line `gcp_project_id`
edit in that environment's `terraform.tfvars`, not a redesign.

## Applying

```bash
cd infra/environments/global
terraform init && terraform plan   # review before applying
terraform apply

cd ../dev   # then test, then prod
terraform init && terraform plan
terraform apply
```

`terraform apply` creates real, billed GCP resources — always review the `plan` output
first. After applying an environment, populate its secrets (never done by Terraform,
see `modules/gcp/secrets`):

```bash
echo -n "$VALUE" | gcloud secrets versions add customer-support-rag-dev-app-api-key \
  --project=project-0fbdbc8d-9379-4cfb-84a --data-file=-
# repeat for groq-api-key, chroma-api-key, chroma-tenant, chroma-database,
# and optionally cohere-api-key/langfuse-public-key/langfuse-secret-key
```

### Redis (Memorystore)

When `enable_vpc_connector = true` (set for `dev` -- see `environments/dev/main.tf`), `apply`
provisions a Basic-tier Memorystore instance plus the Private Services Access peering it
requires. Its host/port aren't known until after `apply`, so -- like every other secret --
Terraform only creates the `redis-url` secret *container*; populate it manually:

```bash
terraform output -raw redis_url   # redis://<internal-ip>:<port>
echo -n "redis://<internal-ip>:<port>" | gcloud secrets versions add customer-support-rag-dev-redis-url \
  --project=project-0fbdbc8d-9379-4cfb-84a --data-file=-
```

`utils/ops.py`'s `SessionStore`/`ResponseCache`/`RateLimiter` all degrade to an in-memory
fallback if `REDIS_URL` is unset or unreachable -- so a missing secret fails soft (each Cloud
Run instance gets its own independent state, silently breaking multi-instance consistency)
rather than hard. Confirm it's actually wired by checking Cloud Run logs for "Redis ... connected"
on startup, not just that `terraform apply` succeeded.

Memorystore Basic tier has an ongoing cost (~1GB instance, no HA) for as long as it exists --
this is a real, billed resource, not something to `apply` casually in a throwaway environment.

### Landing bucket seed data (dev)

`dev`'s ingestion job now reads from the landing bucket like every other environment --
the demo CSV is no longer baked into the image (`INGEST_LEGACY_CSV` was removed from
`environments/dev/main.tf`). After the storage bucket exists, seed it once:

```bash
gcloud storage cp data/flipkart_product_review.csv \
  gs://dev-ingestion-project-0fbdbc8d-9379-4cfb-84a/landing/flipkart_product_review.csv
```

The ingestion job archives it to `gs://<bucket>/archive/` after a successful run (see
`data_ingestion/ingestion_pipeline.py`'s `_archive_files`), so this only needs doing once.

## Adding a second cloud provider

`infra/environments/*/variables.tf`'s `cloud_provider` variable is the parameter point —
currently validated to only accept `"gcp"`. To add AWS or Azure:

1. Implement real resources under `infra/modules/aws/` or `infra/modules/azure/`
   (see the primitive-mapping table in each README.md — e.g. Cloud Run Service → ECS
   Fargate/App Runner on AWS, Container Apps on Azure).
2. Implement `infra/providers/<cloud>/main.tf` composing them, keeping the exact same
   `variables.tf`/`outputs.tf` contract the stub already declares.
3. Relax the `cloud_provider` validation block in each `environments/*/variables.tf`.
4. Add a sibling `module "app_<cloud>"` block in each environment's `main.tf`,
   count-gated on `var.cloud_provider == "<cloud>"`.
5. Add `.github/actions/<cloud>-auth`/`<cloud>-build-push`, and extend
   `.github/workflows/_reusable-deploy.yml`'s provider branch to call them instead of
   failing fast.

## What's deliberately not here yet

- **Redis / Memorystore in test/prod**: `enable_vpc_connector = true` is set for `dev`
  only (`environments/dev/main.tf`) — `test`/`prod` still default to `false`, no
  Memorystore instance, no VPC connector. Flip it on the same way once those
  environments need session/cache persistence across instances too.
- **Prod ingress hardening**: the Cloud Run service currently allows unauthenticated
  invocation at the infrastructure level (`allUsers` invoker) — real access is gated by
  `APP_API_KEY` at the HTTP layer (`main.py`'s auth middleware), matching the old GKE
  setup's posture (`ClusterIP`, no Ingress). IAP/Cloud Armor is a future hardening step,
  not a regression versus what existed before.
