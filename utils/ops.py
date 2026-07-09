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


class ResponseCache:
    def __init__(self):
        self.enabled = os.getenv("CACHE_ENABLED", "true").lower() == "true"
        self.ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
        self.semantic_threshold = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.92"))
        self.redis = self._build_redis_client()
        self.memory_exact: Dict[str, Dict[str, Any]] = {}
        self.memory_semantic: List[Dict[str, Any]] = []

    def _build_redis_client(self):
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return None
        try:
            import redis

            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            logger.info("Redis cache connected.")
            return client
        except Exception:
            logger.exception("Redis cache unavailable; falling back to in-memory cache.")
            return None

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

    def get_semantic(self, query_embedding: List[float], session_id: str) -> Optional[CacheResult]:
        if not self.enabled or not query_embedding:
            return None

        entries = self._semantic_entries()
        best_answer = None
        best_score = 0.0
        for entry in entries:
            if entry.get("session_id") != session_id:
                continue
            score = cosine_similarity(query_embedding, entry.get("embedding", []))
            if score > best_score:
                best_score = score
                best_answer = entry.get("answer")

        if best_answer and best_score >= self.semantic_threshold:
            return CacheResult(answer=best_answer, hit_type="semantic")
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
            self.redis.setex(f"rag:exact:{exact_key}", self.ttl_seconds, exact_payload)
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
        self.redis = self._build_redis_client()
        self.memory_hits: Dict[str, deque] = defaultdict(deque)

    def _build_redis_client(self):
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return None
        try:
            import redis

            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            logger.info("Redis rate limiter connected.")
            return client
        except Exception:
            logger.exception("Redis rate limiter unavailable; falling back to in-memory limits.")
            return None

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


def build_langfuse_trace(trace: RequestTrace):
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse import Langfuse

        return Langfuse().trace(
            id=trace.request_id,
            name="rag-chat",
            input={"question": trace.question, "session_id": trace.session_id},
        )
    except Exception:
        logger.exception("Langfuse trace initialization failed.")
        return None
