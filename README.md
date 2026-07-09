# Customer Support System

FastAPI-based ecommerce product assistant using LangChain, Chroma vector search,
configurable embeddings, and a Groq-hosted LLM.

## Local Setup

```bash
conda create -p env python=3.10 -y
conda activate ./env
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

Required environment variables:

```bash
GOOGLE_API_KEY=
GROQ_API_KEY=
CHROMA_API_KEY=
CHROMA_TENANT=
CHROMA_DATABASE=
APP_API_KEY=
ALLOWED_ORIGINS=http://localhost:8001,http://127.0.0.1:8001
```

`APP_API_KEY` must be sent to protected endpoints in the `X-API-Key` header.
The browser UI prompts for this value and stores it in local storage.

`GOOGLE_API_KEY` is only required when `embedding_model.provider` is `google`.
The default local embedding provider is HuggingFace:

```yaml
embedding_model:
  provider: "huggingface"
  model_name: "sentence-transformers/all-MiniLM-L6-v2"
```

If you change embedding models after inserting documents into Chroma, use a new
collection name or clear the old collection first. Different embedding models
usually produce different vector dimensions.

## Production Readiness Roadmap

The current codebase is a prototype RAG application. The following phased plan
turns it into a production-grade service in priority order.

### Phase 0: Stop the Bleeding

Target: days, not weeks.

- Remove `print(self.groq_api_key)` and all secret logging. Rotate any keys that
  may already have been logged.
- Lock down CORS by replacing `allow_origins=["*"]` with explicit frontend
  domains.
- Add API-key or basic-auth middleware to protect FastAPI endpoints.
- Fix provider naming so config and code consistently describe the actual
  Groq/DeepSeek model.
- Strip DeepSeek-R1 reasoning traces, such as `<think>...</think>`, before
  returning output to users.
- Wrap LLM, Chroma, and embedding calls in `try/except` blocks with safe,
  user-friendly error responses instead of raw 500s.
- Escape or safely render user and model messages in the frontend to avoid
  HTML/script injection.

### Phase 1: Ingestion Overhaul

- Add chunking with `RecursiveCharacterTextSplitter` or semantic chunking,
  including overlap and chunk sizes tuned for the embedding model.
- Preserve document IDs, chunk IDs, and source metadata for traceability.
- Build a dual-index design: keep dense vector search and add BM25/keyword
  search through Elasticsearch, OpenSearch, or `rank_bm25` for small corpora.
- Add incremental ingestion with content hashing, deduplication, and upserts
  instead of blind inserts.
- Run ingestion through a scheduled workflow such as cron, Airflow, or Prefect
  rather than a one-shot script.
- Store metadata such as rating, price, product name, category, and source row
  as filterable structured fields.

### Phase 2: Retrieval Overhaul

- Run dense retrieval and BM25 retrieval in parallel.
- Merge dense and sparse results with Reciprocal Rank Fusion.
- Add a cross-encoder reranker, such as BGE reranker or Cohere Rerank, over
  merged top-20 candidates and pass only the best top-5 to generation.
- Add query rewriting, typo correction, query expansion, and optionally HyDE for
  sparse or ambiguous questions.
- Parse metadata constraints from user queries, such as `rating >= 4`, and pass
  them as structured retrieval filters.
- Replace fixed `k=10` with dynamic retrieval based on score distribution,
  query complexity, and available context budget.

### Phase 3: Generation and Grounding

- Rewrite the prompt to require citations for product claims.
- Add an explicit insufficient-context fallback path.
- Require answers to use only retrieved context unless the system intentionally
  enters a general-help mode.
- Add a faithfulness or groundedness check using RAGAS, an NLI model, or a
  second LLM judge before returning answers.
- Reject, regenerate, or degrade gracefully when groundedness checks fail.
- Add session-scoped conversation memory so retrieval and generation understand
  multi-turn queries.

### Phase 4: Evaluation Framework

- Build a golden test set of real customer questions, expected answers, and
  expected source documents.
- Add retrieval metrics such as recall@k, MRR, context precision, and context
  recall.
- Add answer metrics through RAGAS or DeepEval, including faithfulness and
  answer relevance.
- Run evaluation in CI for every prompt, retrieval, embedding, or model change.
- Block deployment when core RAG quality metrics regress beyond an agreed
  threshold.

### Phase 5: Serving and Ops Hardening

- Add streaming responses through SSE or WebSocket instead of blocking HTTP.
- Add exact-match and semantic caching with Redis.
- Add tracing with LangSmith or Langfuse, including retrieved documents, prompt
  versions, latency, token usage, and model cost.
- Add structured logging, request IDs, health checks, and readiness checks.
- Add API rate limiting and request-size validation.
- Pin dependencies and add vulnerability scanning.
- Improve the Dockerfile with a non-root user, smaller production image, no
  debug file listing, and health checks.
- Deploy with autoscaling, readiness probes, and environment-specific config.

## Recommended Implementation Order

1. Security fixes: secret logging, CORS, auth, input validation, frontend
   escaping.
2. Reliability fixes: error handling, timeout/retry policies, provider naming,
   reasoning-trace stripping.
3. Retrieval quality: chunking, metadata, hybrid search, reranking.
4. Grounded generation: citation prompt, insufficient-context behavior,
   groundedness checks.
5. Quality gates: golden set, automated RAG evaluation, CI enforcement.
6. Operations: streaming, caching, tracing, deployment hardening.
