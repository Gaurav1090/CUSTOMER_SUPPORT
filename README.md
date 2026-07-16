# Customer Support System

A FastAPI-based ecommerce product assistant: hybrid (dense + BM25) retrieval
over a Chroma vector store, optional Cohere semantic reranking, conversational
query rewriting for multi-turn chat, and grounded generation with citation
verification and an LLM groundedness judge. LLM and embedding providers are
swappable (Groq / Google Gemini / HuggingFace) via `config/config.yaml`.

## Architecture

```
User (web UI or API client)
        |
        v
FastAPI (main.py)
  - X-API-Key auth on /get, /get/stream
  - per-identity rate limiting
  - exact + semantic response cache
        |
        v
Query contextualization (retriever/query_rewriter.py)
  - resolves follow-ups ("what about a cheaper one?") into a standalone
    query using chat history, via a small/fast LLM
  - skipped entirely on a session's first turn
        |
        v
Hybrid retrieval (retriever/retrieval.py)
  - dense search (Chroma) + BM25 keyword search, run concurrently
  - metadata filters parsed from the query (rating>=4, category:x, ...)
  - Reciprocal Rank Fusion merge
        |
        v
Reranking
  - Cohere Rerank when COHERE_API_KEY is set (wider candidate pool)
  - lexical term-overlap fallback otherwise (narrower pool, logged loudly)
        |
        v
Generation (prompt_library/prompt.py + utils/model_loader.py)
  - context chunks delimited in <doc source="..."> tags (prompt-injection
    defense: model is told to treat them as data, not instructions)
  - citation required in [source:ID] form
        |
        v
Guardrails
  - citation check: flags answers citing a source that wasn't retrieved
  - LLM-as-judge groundedness check
  - either failing -> safe "Insufficient context" fallback, not a guess
        |
        v
Response to user + session history persisted (Redis-backed, in-memory fallback)
```

## Project structure

```
main.py                      FastAPI app: routes, auth, caching, the request pipeline
config/config.yaml           Model providers, retrieval, ingestion settings
retriever/
  retrieval.py                Hybrid search, RRF, reranking, metadata filters
  query_rewriter.py           Multi-turn query contextualization
data_ingestion/
  ingestion_pipeline.py        Incremental ingest: land -> clean -> chunk -> dedupe -> embed
utils/
  model_loader.py              LLM/embedding provider loading (groq/google/huggingface)
  chroma_utils.py               Chroma Cloud vs local persistence routing
  ops.py                        ResponseCache, RateLimiter, SessionStore (Redis-backed,
                                 in-memory fallback), request tracing
  bm25_index.py, object_store.py, config_loader.py
prompt_library/prompt.py      System prompts (generation, groundedness judge, query rewrite)
evaluation/
  golden_test_set.py           12-case labeled test set across recommendation, comparison,
                                metadata-filter, out-of-scope, multi-turn, and prompt-injection cases
  evaluator.py                  Retrieval (precision/recall/MRR) + generation (faithfulness/
                                 relevance) metrics; uses RAGAS if installed, else a fast fallback
  run_evaluation.py             Runs the golden set end-to-end, gates CI on regression vs. baseline
tests/                        70 tests: fast unit tests (no live deps) + a few CI-only
                               live tests (test_phase4_ci.py) that hit real providers
templates/, static/           Web chat UI
deploy/k8s.yaml, Dockerfile,
docker-compose.yml             Deployment manifests (not covered in depth here)
```

## Prerequisites

- Python 3.12 (see `.python-version`)
- API keys for whichever providers you enable (see Configuration below) --
  at minimum one LLM provider and Chroma Cloud credentials, since there's no
  local Chroma emulator
- Docker, only if you want to test against a real local Redis instead of the
  in-memory fallback

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in what you need (see Configuration
below for which keys are required for your chosen providers). At minimum:

```bash
cp .env.example .env
# edit .env: APP_API_KEY, one LLM provider's key, CHROMA_API_KEY/TENANT/DATABASE
```

Ingest the bundled demo dataset (450 Flipkart product reviews) into your
Chroma collection -- one-time, safe to re-run (incremental, deduped by
content hash):

```bash
INGEST_LEGACY_CSV=true python -m data_ingestion.ingestion_pipeline
```

This populates whatever collection `config/config.yaml`'s `chroma.collection_name`
points at, using whatever `embedding_model` is configured. **If you change
the embedding provider/model later, you must re-ingest into a new collection
name** -- different embedding models produce different vector spaces and
can't share a collection.

## Running it yourself

```bash
uvicorn main:app --reload --port 8001
```

Then verify:

```bash
curl http://localhost:8001/health
# {"status":"healthy"}

curl http://localhost:8001/ready
# {"status":"ready","checks":{"app_api_key":true,"groq_api_key":true,"chroma_storage":true}}
```

Open `http://localhost:8001` for the chat UI, or drive it directly:

```bash
# single turn
curl -X POST http://localhost:8001/get \
  -H "X-API-Key: $APP_API_KEY" \
  -H "X-Session-Id: user-123" \
  --data-urlencode "msg=Can you recommend a good budget headphone?"

# follow-up in the same session -- query contextualization resolves
# "a more premium one" using the prior turn automatically
curl -X POST http://localhost:8001/get \
  -H "X-API-Key: $APP_API_KEY" \
  -H "X-Session-Id: user-123" \
  --data-urlencode "msg=What about a more premium option instead?"

# streaming (SSE)
curl -N -X POST http://localhost:8001/get/stream \
  -H "X-API-Key: $APP_API_KEY" \
  -H "X-Session-Id: user-123" \
  --data-urlencode "msg=What do people say about the realme Buds Q?"
```

```python
import requests

BASE_URL, API_KEY = "http://localhost:8001", "your-app-api-key"

def ask(question, session_id="default"):
    resp = requests.post(
        f"{BASE_URL}/get",
        data={"msg": question},
        headers={"X-API-Key": API_KEY, "X-Session-Id": session_id},
    )
    resp.raise_for_status()
    return resp.text

print(ask("What headphones do you recommend?", session_id="user-1"))
print(ask("Do they have noise cancellation?", session_id="user-1"))  # multi-turn
```

### Running the test suite

```bash
python -m unittest discover tests -p "test_*.py" -v
```

70 tests, all fast and dependency-free except `tests/test_phase4_ci.py`,
which instantiates a real `Retriever()` and calls real providers -- expect
that one to consume LLM/Chroma/Cohere quota when you run it.

### Running the evaluation framework

```bash
python -m evaluation.run_evaluation
```

Runs the 12-case golden set end-to-end against your currently configured
providers, writes `evaluation/results.json`, and exits non-zero if
`mean_score` regresses more than the configured tolerance against
`evaluation/baseline_results.json` (this is what gates CI). This makes
several real LLM calls -- expect it to take a couple of minutes and to
consume meaningful quota on whichever provider you have configured.

## Configuration

### LLM and embedding providers

Both are independently swappable in `config/config.yaml` via `utils/model_loader.py`.
No code changes needed to switch -- just the config block and the matching
env var.

For the LLM specifically, you don't even need to edit `config.yaml`: set
`LLM_PROVIDER` (`groq`/`google`/`huggingface`), `LLM_MODEL_NAME`, and/or
`LLM_REWRITE_MODEL_NAME` in `.env` (see `.env.example`) and they take
precedence over the config file. This is the fast path for hopping
providers the moment you hit a rate limit or daily quota mid-session --
just make sure the matching API key for whatever you switch to is also
set. Embedding provider is deliberately **not** env-switchable the same
way -- swapping it means re-ingesting into a new collection with matching
vector dimensions (see the ingestion note further down), so that one
stays a deliberate `config.yaml` edit.

Example: switching to HuggingFace mid-session. Model availability on the
router shifts over time (see the `huggingface` row below), so verify
first with `curl -s https://router.huggingface.co/v1/models | jq '.data[].id'`
-- these two were live and cheap at time of writing:

```
LLM_PROVIDER=huggingface
LLM_MODEL_NAME=meta-llama/Llama-3.3-70B-Instruct
LLM_REWRITE_MODEL_NAME=meta-llama/Llama-3.1-8B-Instruct
HF_TOKEN=your-token
```

`Llama-3.3-70B-Instruct` mirrors the current Groq default model for the
main generation model; `Llama-3.1-8B-Instruct` is the cheapest/fastest
option on the router for the query-rewrite model, same role
`llama-3.1-8b-instant` plays on Groq.

| `provider` | Applies to | Env var | Notes |
|---|---|---|---|
| `groq` | `llm` | `GROQ_API_KEY` | Fast, free tier -- but a **daily** token cap (100k TPD observed on `llama-3.3-70b-versatile`) that resets on a fixed daily cycle, not a rolling window. Automated testing burns through it fast. |
| `google` | `llm` and/or `embedding_model` | `GOOGLE_API_KEY` | Free tier exists for `gemini-2.5-flash`/`gemini-2.5-flash-lite` and `gemini-embedding-001` -- **but only if the API key's project has no Cloud Billing account linked.** A billing-linked project draws down a separate "Prepay" credit balance instead, and once that hits $0 every key on the billing account fails with a `RESOURCE_EXHAUSTED` / "prepayment credits are depleted" error -- a different failure mode than a rate limit, easy to hit by accident. Create a fresh key with no billing account attached for the real free tier. |
| `huggingface` | `llm` and/or `embedding_model` | `HF_TOKEN` | `embedding_model` runs `sentence-transformers/all-MiniLM-L6-v2` **locally** (no API, no quota risk -- this is the most quota-robust embedding option). `llm` calls HF's serverless Inference Providers router, which has its own small **monthly** credit pool, separate from Groq/Google -- a single evaluation run against a 70B model can exhaust it. Model availability on the free router also shifts over time; check `curl -s https://router.huggingface.co/v1/models` for what's currently live. Get a plain "Read" scope token at huggingface.co/settings/tokens -- no billing account involved in that flow. |

Current default: embeddings on local HuggingFace (no API, no quota risk),
generation on Groq. Every "free tier" above has a real, easy-to-hit limit in
practice -- if you're doing heavy iterative testing, expect to rotate
providers, and budget for that when picking one for production traffic.

### Reranking

`COHERE_API_KEY` enables Cohere Rerank over the merged dense+BM25 candidates.
Cohere's trial key is limited to 10 calls/minute -- fine for interactive use,
easy to exhaust in an automated evaluation run. Without a key, retrieval
falls back to lexical term-overlap reranking and logs a warning on every
query so degraded mode is never silent.

### Redis (session storage, response cache, rate limiting)

`REDIS_URL` backs three independent things in `utils/ops.py`:
`SessionStore` (per-session chat history), `ResponseCache` (exact + semantic
answer caching), and `RateLimiter`. All three fall back to an in-memory
equivalent when `REDIS_URL` is unset, logged loudly when that happens. The
in-memory fallback is correct for a single local process, but:

- multi-turn chat history only stays consistent as long as the same
  process/replica keeps handling that session -- silently breaks under
  multiple replicas or a restart
- managed Redis (e.g. GCP Memorystore) is typically **VPC-private by
  default** -- reachable from services running inside that VPC (like a real
  GKE deployment), not from an arbitrary local dev machine or CI runner

To test the Redis-backed path for real:

```bash
docker run -d -p 6379:6379 redis:7
REDIS_URL=redis://localhost:6379 uvicorn main:app --reload --port 8001
```

Or for fast, dependency-free coverage of the same code paths without any
external service: `python -m unittest tests.test_redis_backed -v` (uses
`fakeredis`, an in-process Redis-protocol implementation -- validates real
Redis command semantics, no network involved).

### Production monitoring (Langfuse)

Every single request -- not just eval runs -- already computes a hallucination
signal per `main.py`'s `invoke_chain_details`: `citation_check` (did the
answer cite a source_id that wasn't actually retrieved?) and
`groundedness_verdict` (did the LLM-as-judge say the answer is supported by
the retrieved context?), plus retrieval/generation latency and cache hit
type. Setting `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` in `.env` sends all
of that to [Langfuse](https://langfuse.com) (free Cloud tier or self-hosted)
as a proper per-request trace, with `citation_check` and `groundedness`
recorded as first-class Langfuse **scores** -- not just metadata -- so
they're directly chartable in the Langfuse dashboard as trend lines (e.g.
"groundedness pass rate over the last 7 days"). That trend is the actual
answer to "is the app's quality degrading in production": a citation/
groundedness pass-rate that's drifting down is the hallucination-rate signal,
observable without waiting for the next `evaluation/run_evaluation.py` run.

Each trace's ID is deterministically derived from the request's own
`request_id` (`Langfuse.create_trace_id(seed=request_id)`), so a Langfuse
trace can always be cross-referenced back to the matching `RequestTrace` JSON
log line (see the "Structured request tracing" known limitation below --
you need `logging.basicConfig()` configured for that log line to actually go
anywhere).

`utils/ops.py`'s `build_langfuse_trace`/`finish_langfuse_trace` use the
OpenTelemetry-based span API from the Langfuse **v3+** SDK
(`requirements-optional.txt` pins `langfuse>=3,<5`) -- the older `.trace()`
call this replaced was removed in that rewrite and would silently no-op
(caught by a broad `except`, span always `None`, nothing ever reaching the
dashboard) on any modern `pip install langfuse`. Both helpers are fully
optional: unset the two keys and every call becomes a no-op, same as today.

### Other env vars

See `.env.example` for the full list with inline explanations: `CACHE_ENABLED`/
`CACHE_TTL_SECONDS`/`SEMANTIC_CACHE_THRESHOLD`, `RATE_LIMIT_REQUESTS`/
`RATE_LIMIT_WINDOW_SECONDS`, `SESSION_TTL_SECONDS`/`SESSION_MAX_TURNS`,
`CHROMA_STORAGE_MODE`, and `LANDING_PATH`/`INDEX_PATH` (ingestion source/state
location -- can point at `gs://`/`s3://`/`abfs://` in prod).

## Known limitations

- **The web UI has no per-browser session ID.** `templates/chat.html` never
  sends an `X-Session-Id` header, so every browser tab defaults to
  `session_id="default"` on the server -- concurrent web UI users currently
  share one global conversation history. The API-level session isolation
  (via the `X-Session-Id` header, used throughout the examples above) works
  correctly; the UI just doesn't exercise it yet.
- **Structured request tracing doesn't surface in a real run.** `utils/ops.py`'s
  `RequestTrace` logs a JSON event per request (retrieval/generation latency,
  citation check, groundedness verdict, cache hit type) via `logging`, but
  nothing in the app calls `logging.basicConfig()` -- so under plain
  `uvicorn main:app`, those `INFO`-level logs have no handler and go
  nowhere. They only appear if you configure logging yourself (as the
  examples in this README's development workflow do).
- **Metadata filters for `price`/`category`/`brand` don't do anything against
  the bundled demo dataset.** The Flipkart CSV only has
  `product_id`/`product_title`/`rating`/`summary`/`review` columns, so
  `retriever/retrieval.py`'s filter parser recognizes those query terms but
  they never match any ingested metadata. `rating>=N` does work.
  - This is fine, and correct grounded behavior -- but it means the LLM is
    occasionally willing to answer from tangentially related context instead
    of refusing, on out-of-scope questions specifically.
- **`llm.provider: "groq"`'s daily quota and `"google"`'s billing trap are
  both real, encountered firsthand** -- see the Configuration table above
  before picking a provider for anything beyond light local testing.

## Deployment

Deployed on **Google Cloud Run** (migrated 2026-07-15 from an earlier GKE-based setup --
`git log` still has `deploy/k8s.yaml` if you need to compare). Full module/environment
layout and how to add a second cloud provider live in [`infra/README.md`](infra/README.md);
this section is the practical summary.

`docker-compose.yml` deliberately has no local Redis service -- `REDIS_URL` is expected
to point at a real managed Redis even in that context.

### Environments

| Environment | Deploys from | Terraform root | Status |
|---|---|---|---|
| dev  | `developer` branch | `infra/environments/dev`  | **Live**, verified end-to-end 2026-07-16 |
| test | `staging` branch   | `infra/environments/test` | Not yet applied |
| prod | `main` branch      | `infra/environments/prod` | Not yet applied |

Each environment is fully isolated: its own Terraform state prefix, its own deployer +
runtime service accounts (least-privilege, branch-scoped via Workload Identity
Federation so a `developer`-branch CI run can never deploy `prod`), its own Cloud Run
service + ingestion job, Secret Manager secrets, and GCS bucket for ingestion
landing/index storage.

### CI/CD

- `ci-fast-tests.yml` -- the 82-test unit suite, every push/PR, no live API calls.
- `cd-dev.yml` / `cd-test.yml` / `cd-prod.yml` -- branch-triggered: tests -> build (once;
  the same image is promoted across environments, never rebuilt per environment) ->
  deploy (runs the ingestion job, then the Cloud Run service, then a `/health`+`/ready`
  smoke test).
- `rag-evaluation.yml` -- the quota-heavy live-provider evaluation. Only runs before a
  prod deploy or on manual `workflow_dispatch`, deliberately off the routine path so it
  doesn't burn Groq/Chroma/Cohere quota on every commit.

### Standing up a new environment

```bash
cd infra/environments/<env>
terraform init && terraform plan   # review before applying -- creates real billed resources
terraform apply

# Populate secrets (Terraform only creates the containers, never values):
echo -n "$VALUE" | gcloud secrets versions add customer-support-rag-<env>-app-api-key \
  --project=<project-id> --data-file=-
# repeat for groq-api-key, chroma-api-key, chroma-tenant, chroma-database, etc.
```

Then create the matching GitHub Environment (repo Settings -> Environments) with
`GCP_WIF_PROVIDER`, `GCP_DEPLOYER_SA_EMAIL`, `GCP_REGION`, `GCP_PROJECT_ID`,
`CLOUD_RUN_SERVICE_NAME`, `CLOUD_RUN_JOB_NAME` as variables, plus the repo-level
`GCP_WIF_PROVIDER`/`GCP_BUILDER_SA_EMAIL`/`GCP_REGION`/`GCP_PROJECT_ID`/
`GCP_ARTIFACT_REPOSITORY_ID` the build step needs (see
`.github/workflows/_reusable-build.yml`/`_reusable-deploy.yml` for exactly which ones).

### Real bugs hit standing up `dev` (worth knowing before repeating this for test/prod)

Every one of these was an actual failure on the first real deploy, not a hypothetical:

- An unquoted YAML description mixing `"quotes"` and `{braces}` got the *entire*
  workflow file silently rejected by GitHub with zero jobs created -- no job-level
  error to debug from, since nothing ran at all.
- Reusable workflow jobs only get the permissions the *caller* explicitly grants
  (`id-token: write` for WIF auth here) -- declaring them in the reusable file alone
  isn't enough.
- A local composite action (`./.github/actions/gcp-auth`) needs `actions/checkout` in
  the same job first, or it can't find its own `action.yml`.
- The deployer service account needs `roles/artifactregistry.reader` alongside
  `roles/run.admin` -- otherwise it can push an image it then can't pull back down.
- `roles/storage.objectAdmin` on a GCS bucket grants **zero** bucket-level permissions
  (object-level only) -- `gcsfs`'s existence check needs `roles/storage.legacyBucketReader`
  too, or it fails with a misleading "bucket does not exist" even though it's right there.
- `google_service_account.account_id` has a 30-character limit and GCS bucket names have
  a 63-character limit -- naive `${app_name}-${environment}-<suffix>` naming hit both.
- Cloud Run's `deletion_protection` defaults to `true` and blocks even a legitimate
  destroy-and-replace of a tainted resource within the same apply -- set explicitly to
  `false`, since Terraform is the sole owner of these resources here.
- Behind Cloud Run's TLS-terminating proxy, `uvicorn` needs `--proxy-headers
  --forwarded-allow-ips='*'`, or `url_for()`-generated URLs come back `http://` on an
  `https://` page -- browsers block that as mixed content, breaking the chat UI's own
  stylesheet while external CDN assets kept loading fine.

### Verified live

```bash
$ curl https://customer-support-rag-dev-udytqlhsma-uw.a.run.app/health
{"status":"healthy"}
$ curl https://customer-support-rag-dev-udytqlhsma-uw.a.run.app/ready
{"status":"ready","checks":{"app_api_key":true,"groq_api_key":true,"chroma_storage":true}}
```

Real ingestion ran end to end (542 chunks from the bundled demo dataset into Chroma
Cloud + the BM25 index), and a real query through the deployed app returned a
correctly-grounded, cited answer -- not just health checks passing.
