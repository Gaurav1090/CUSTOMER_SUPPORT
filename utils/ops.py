import hashlib
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from math import sqrt
from typing import Any, Dict, Iterable, List, Optional

from utils.pii import redact_pii

logger = logging.getLogger(__name__)


def new_request_id() -> str:
    return str(uuid.uuid4())


def normalize_query(query: str) -> str:
    return " ".join(query.lower().strip().split())


def cache_key(query: str, session_id: str) -> str:
    payload = f"{session_id}:{normalize_query(query)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    if not left_values or not right_values or len(left_values) != len(right_values):
        return 0.0

    dot = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = sqrt(sum(a * a for a in left_values))
    right_norm = sqrt(sum(b * b for b in right_values))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass
class CacheResult:
    answer: str
    hit_type: str


_nli_model = None
_nli_model_load_failed = False


def _get_nli_model():
    """Lazily load a single shared CrossEncoder NLI model for the process
    lifetime (unlike utils/model_loader.py's LLM, this one has no reason to
    be swappable per-request, so a module-level singleton is correct here --
    reloading it per call would be the same per-request-instantiation
    mistake found in build_langfuse_trace())."""
    global _nli_model, _nli_model_load_failed
    if _nli_model is not None or _nli_model_load_failed:
        return _nli_model
    try:
        from sentence_transformers import CrossEncoder

        model_name = os.getenv("SEMANTIC_CACHE_NLI_MODEL", "cross-encoder/nli-deberta-v3-small")
        _nli_model = CrossEncoder(model_name)
        logger.info("Semantic cache NLI model loaded: %s", model_name)
    except Exception:
        logger.exception("Failed to load semantic cache NLI model; semantic cache disabled.")
        _nli_model_load_failed = True
    return _nli_model


def _is_paraphrase(cached_query: str, incoming_query: str) -> bool:
    """True only if incoming_query is a reworded restatement of cached_query,
    not merely topically similar and not a negated/opposite question.

    Cosine similarity on sentence embeddings can't tell these apart -- e.g.
    on all-MiniLM-L6-v2, "good battery life" vs "poor battery life" scores
    *higher* (~0.97) than a genuine paraphrase (~0.89), because negation
    barely shifts embedding space. An NLI cross-encoder is used instead:
    require entailment forward (cached -> incoming) and no contradiction
    reverse (incoming -> cached). Both checks are needed -- on the "is it
    worth buying" / "is it not worth buying" pair, the reverse direction
    alone gave a weak, ambiguous entailment signal, but the forward
    direction correctly flagged contradiction.
    """
    nli = _get_nli_model()
    if nli is None:
        return False

    labels = nli.config.id2label
    scores = nli.predict([(cached_query, incoming_query), (incoming_query, cached_query)])
    forward_label = labels[int(scores[0].argmax())]
    reverse_label = labels[int(scores[1].argmax())]
    return forward_label == "entailment" and reverse_label != "contradiction"


def _build_redis_client(purpose: str):
    """Connect to REDIS_URL if set, else None (caller falls back to
    in-memory). Shared by ResponseCache/RateLimiter/SessionStore so the
    connect-and-log-loudly-on-failure behavior stays identical across all
    three instead of drifting between copies."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    try:
        import redis

        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        logger.info("Redis %s connected.", purpose)
        return client
    except Exception:
        logger.exception("Redis %s unavailable; falling back to in-memory %s.", purpose, purpose)
        return None


class ResponseCache:
    def __init__(self):
        self.enabled = os.getenv("CACHE_ENABLED", "true").lower() == "true"
        self.ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
        # Cheap cosine pre-filter only -- NOT the final hit decision. Cosine
        # similarity alone can't separate paraphrases from negated opposites
        # (see _is_paraphrase), so this just narrows candidates worth the
        # more expensive NLI check. Genuine paraphrases measured ~0.89 on
        # all-MiniLM-L6-v2 vs ~0.55-0.64 for same-product-different-feature
        # questions, so 0.80 comfortably keeps the former as candidates
        # while skipping NLI on the latter.
        self.semantic_candidate_threshold = float(os.getenv("SEMANTIC_CACHE_CANDIDATE_THRESHOLD", "0.80"))
        self.redis = _build_redis_client("cache")
        self.memory_exact: Dict[str, Dict[str, Any]] = {}
        self.memory_semantic: List[Dict[str, Any]] = []

    def get_exact(self, query: str, session_id: str) -> Optional[CacheResult]:
        if not self.enabled:
            return None

        key = cache_key(query, session_id)
        if self.redis:
            payload = self.redis.get(f"rag:exact:{key}")
            if payload:
                return CacheResult(answer=json.loads(payload)["answer"], hit_type="exact")
            return None

        payload = self.memory_exact.get(key)
        if payload and payload["expires_at"] > time.time():
            return CacheResult(answer=payload["answer"], hit_type="exact")
        self.memory_exact.pop(key, None)
        return None

    def get_semantic(self, query: str, query_embedding: List[float], session_id: str) -> Optional[CacheResult]:
        if not self.enabled or not query_embedding:
            return None

        entries = self._semantic_entries()
        candidates = []
        for entry in entries:
            if entry.get("session_id") != session_id:
                continue
            score = cosine_similarity(query_embedding, entry.get("embedding", []))
            if score >= self.semantic_candidate_threshold:
                candidates.append((score, entry))
        candidates.sort(key=lambda pair: pair[0], reverse=True)

        # Cosine similarity alone can rank a negated opposite above a real
        # paraphrase (see _is_paraphrase), so every candidate must also pass
        # the NLI entailment gate -- highest-cosine first, first pass wins.
        max_candidates = int(os.getenv("SEMANTIC_CACHE_MAX_NLI_CHECKS", "5"))
        for _, entry in candidates[:max_candidates]:
            cached_query = entry.get("query", "")
            if cached_query and _is_paraphrase(cached_query, query):
                return CacheResult(answer=entry.get("answer"), hit_type="semantic")
        return None

    def set(self, query: str, session_id: str, answer: str, query_embedding: Optional[List[float]] = None) -> None:
        if not self.enabled:
            return

        exact_key = cache_key(query, session_id)
        exact_payload = json.dumps({"answer": answer})
        semantic_payload = {
            "query": normalize_query(query),
            "session_id": session_id,
            "answer": answer,
            "embedding": query_embedding or [],
            "expires_at": time.time() + self.ttl_seconds,
        }

        if self.redis:
            self.redis.set(f"rag:exact:{exact_key}", exact_payload, ex=self.ttl_seconds)
            if query_embedding:
                self.redis.lpush("rag:semantic:index", json.dumps(semantic_payload))
                self.redis.ltrim("rag:semantic:index", 0, int(os.getenv("SEMANTIC_CACHE_MAX_ENTRIES", "500")) - 1)
            return

        self.memory_exact[exact_key] = {"answer": answer, "expires_at": time.time() + self.ttl_seconds}
        if query_embedding:
            self.memory_semantic.insert(0, semantic_payload)
            max_entries = int(os.getenv("SEMANTIC_CACHE_MAX_ENTRIES", "500"))
            del self.memory_semantic[max_entries:]

    def _semantic_entries(self) -> List[Dict[str, Any]]:
        if self.redis:
            raw_entries = self.redis.lrange("rag:semantic:index", 0, int(os.getenv("SEMANTIC_CACHE_MAX_ENTRIES", "500")) - 1)
            entries = []
            now = time.time()
            for raw_entry in raw_entries:
                try:
                    entry = json.loads(raw_entry)
                except json.JSONDecodeError:
                    continue
                if entry.get("expires_at", 0) > now:
                    entries.append(entry)
            return entries

        now = time.time()
        self.memory_semantic = [entry for entry in self.memory_semantic if entry.get("expires_at", 0) > now]
        return self.memory_semantic


class RateLimiter:
    def __init__(self):
        self.limit = int(os.getenv("RATE_LIMIT_REQUESTS", "30"))
        self.window_seconds = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
        self.redis = _build_redis_client("rate limiter")
        self.memory_hits: Dict[str, deque] = defaultdict(deque)

    def allow(self, identity: str) -> bool:
        if self.limit <= 0:
            return True

        if self.redis:
            key = f"rag:rate:{identity}"
            current = self.redis.incr(key)
            if current == 1:
                self.redis.expire(key, self.window_seconds)
            return current <= self.limit

        now = time.time()
        hits = self.memory_hits[identity]
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


class SessionStore:
    """Per-session chat history, Redis-backed with in-memory fallback --
    same connect/degrade pattern as ResponseCache/RateLimiter. Redis-backed
    so multi-turn history survives a process restart and stays consistent
    if this ever runs as multiple replicas; the in-memory fallback keeps
    history local to whichever process/replica handled each request, which
    silently breaks multi-turn context the moment there's more than one."""

    def __init__(self):
        self.ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "86400"))
        self.max_turns = int(os.getenv("SESSION_MAX_TURNS", "20"))
        self.redis = _build_redis_client("session store")
        self.memory: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    def append(self, session_id: str, user: str, assistant: str) -> None:
        turn = {"user": user, "assistant": assistant}

        if self.redis:
            key = f"rag:session:{session_id}"
            self.redis.rpush(key, json.dumps(turn))
            self.redis.ltrim(key, -self.max_turns, -1)
            self.redis.expire(key, self.ttl_seconds)
            return

        history = self.memory[session_id]
        history.append(turn)
        del history[: -self.max_turns]

    def get_recent(self, session_id: str, limit: int = 4) -> List[Dict[str, str]]:
        if self.redis:
            raw_entries = self.redis.lrange(f"rag:session:{session_id}", -limit, -1)
            turns = []
            for raw_entry in raw_entries:
                try:
                    turns.append(json.loads(raw_entry))
                except json.JSONDecodeError:
                    continue
            return turns

        return self.memory.get(session_id, [])[-limit:]


@dataclass
class RequestTrace:
    request_id: str
    question: str
    session_id: str
    start_time: float = field(default_factory=time.time)
    events: Dict[str, Any] = field(default_factory=dict)

    def add(self, key: str, value: Any) -> None:
        self.events[key] = value

    def finish(self, status: str, error: Optional[str] = None) -> None:
        latency_ms = int((time.time() - self.start_time) * 1000)
        payload = {
            "event": "rag_request",
            "request_id": self.request_id,
            "session_id": self.session_id,
            "status": status,
            "latency_ms": latency_ms,
            "question_length": len(self.question),
            **self.events,
        }
        if error:
            payload["error"] = error
        logger.info(json.dumps(payload, default=str))


_langfuse_client = None
_langfuse_client_init_failed = False


def _get_langfuse_client():
    """Lazily build a single shared Langfuse client for the process
    lifetime. Constructing Langfuse() sets up its OTel exporter/tracer
    provider, which measured ~5.9s when done per-request -- trivial next
    to a normal 8-18s retrieval+generation request, but it was the
    dominant cost on a cache hit, where everything else is skipped."""
    global _langfuse_client, _langfuse_client_init_failed
    if _langfuse_client is not None or _langfuse_client_init_failed:
        return _langfuse_client
    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse()
    except Exception:
        logger.exception("Langfuse client initialization failed.")
        _langfuse_client_init_failed = True
    return _langfuse_client


def build_langfuse_trace(trace: RequestTrace):
    """Start a Langfuse span for this request, tagged with a trace ID
    deterministically derived from our own request_id (so a RequestTrace
    JSON log line and its Langfuse trace can be cross-referenced by that
    ID). Returns None -- and the caller just skips Langfuse entirely --
    when the keys aren't set or the SDK call fails for any reason,
    including an incompatible langfuse-python version: the old `.trace()`
    call this replaced was removed in the v3+ OpenTelemetry-based SDK
    rewrite, which made every Langfuse call here silently no-op (caught by
    this same except, span always None) on any langfuse>=3 install --
    tracing looked wired up but nothing ever reached the dashboard."""
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    try:
        client = _get_langfuse_client()
        if client is None:
            return None
        trace_id = client.create_trace_id(seed=trace.request_id)
        return client.start_observation(
            trace_context={"trace_id": trace_id},
            name="rag-chat",
            as_type="span",
            input={"question": redact_pii(trace.question), "session_id": trace.session_id},
            metadata={"session_id": trace.session_id},
        )
    except Exception:
        logger.exception("Langfuse trace initialization failed.")
        return None


def finish_langfuse_trace(
    span, trace: RequestTrace, output: Optional[str] = None, error: Optional[str] = None
) -> None:
    """Attach the final answer, the full RequestTrace event payload, and
    the citation/groundedness verdicts as first-class Langfuse scores (so
    they show up as chartable trend lines in the Langfuse dashboard --
    e.g. "citation_check pass rate over the last 7 days" -- instead of
    being buried, unqueryable, inside metadata JSON) before ending the
    span. A no-op if span is None (Langfuse disabled/unavailable), and
    never lets an observability failure break the actual response."""
    if span is None:
        return
    try:
        span.update(
            output={"answer": redact_pii(output)} if output is not None else None,
            metadata=dict(trace.events),
            level="ERROR" if error else "DEFAULT",
            status_message=error,
        )
        if trace.events.get("citation_check") in ("passed", "failed"):
            span.score(
                name="citation_check",
                value=1.0 if trace.events["citation_check"] == "passed" else 0.0,
                data_type="BOOLEAN",
            )
        if trace.events.get("groundedness_verdict") in ("passed", "failed"):
            span.score(
                name="groundedness",
                value=1.0 if trace.events["groundedness_verdict"] == "passed" else 0.0,
                data_type="BOOLEAN",
            )
        span.end()
    except Exception:
        logger.exception("Failed to finalize Langfuse trace.")


def start_llm_generation(parent_span, name: str, model: Optional[str], input_data: Optional[Any] = None):
    """Start a nested Langfuse *generation* observation under parent_span
    for a single LLM call. Distinct from the plain "span" build_langfuse_trace
    creates -- only an as_type="generation" observation with a model name
    carries usage_details, which is what makes Langfuse's own cost
    dashboard compute per-model/per-step token cost automatically. Returns
    None (and the caller skips finish_llm_generation too) when Langfuse is
    disabled/unavailable, same no-op-on-failure pattern as
    build_langfuse_trace -- an observability hiccup must never break the
    actual LLM call it's wrapping."""
    if parent_span is None:
        return None
    try:
        redacted_input = (
            {key: redact_pii(value) if isinstance(value, str) else value for key, value in input_data.items()}
            if isinstance(input_data, dict)
            else redact_pii(input_data) if isinstance(input_data, str) else input_data
        )
        return parent_span.start_observation(name=name, as_type="generation", model=model, input=redacted_input)
    except Exception:
        logger.exception("Failed to start Langfuse generation observation: %s", name)
        return None


def finish_llm_generation(generation, output: Optional[str], usage_metadata: Optional[Dict[str, Any]]) -> None:
    """End a generation observation started by start_llm_generation,
    translating LangChain's usage_metadata keys (input_tokens/output_tokens/
    total_tokens -- present on AIMessage when the provider reports usage,
    None otherwise) into Langfuse's usage_details schema (input/output/total)."""
    if generation is None:
        return
    try:
        usage_details = None
        if usage_metadata:
            usage_details = {
                "input": usage_metadata.get("input_tokens"),
                "output": usage_metadata.get("output_tokens"),
                "total": usage_metadata.get("total_tokens"),
            }
        generation.update(output=redact_pii(output), usage_details=usage_details)
        generation.end()
    except Exception:
        logger.exception("Failed to finalize Langfuse generation observation.")
