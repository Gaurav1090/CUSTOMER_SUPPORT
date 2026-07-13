import os
import unittest
from collections import defaultdict, deque

import fakeredis

from utils.ops import RateLimiter, ResponseCache, SessionStore, _build_redis_client, cache_key


def _make_response_cache(redis_client):
    """Build a ResponseCache without going through __init__ (which would
    try to read REDIS_URL from the real environment) -- same __new__ +
    manual-attribute pattern already used for Retriever in
    tests/test_retrieval_logic.py."""
    cache = ResponseCache.__new__(ResponseCache)
    cache.enabled = True
    cache.ttl_seconds = 3600
    cache.semantic_threshold = 0.92
    cache.redis = redis_client
    cache.memory_exact = {}
    cache.memory_semantic = []
    return cache


def _make_rate_limiter(redis_client, limit=3, window=60):
    limiter = RateLimiter.__new__(RateLimiter)
    limiter.limit = limit
    limiter.window_seconds = window
    limiter.redis = redis_client
    limiter.memory_hits = defaultdict(deque)
    return limiter


def _make_session_store(redis_client, max_turns=20, ttl_seconds=86400):
    store = SessionStore.__new__(SessionStore)
    store.ttl_seconds = ttl_seconds
    store.max_turns = max_turns
    store.redis = redis_client
    store.memory = defaultdict(list)
    return store


class ResponseCacheRedisTests(unittest.TestCase):
    """Exercises ResponseCache against fakeredis -- a real (in-process)
    Redis command implementation, not a mock -- so this validates the
    actual GET/SETEX/LPUSH/LTRIM usage against real Redis semantics, which
    had never been tested before (REDIS_URL was never set in this repo)."""

    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.cache = _make_response_cache(self.redis)

    def test_exact_cache_hit_after_set(self):
        self.cache.set("cheap earbuds", "s1", "The OnePlus Bullets are a good pick.")
        result = self.cache.get_exact("cheap earbuds", "s1")
        self.assertIsNotNone(result)
        self.assertEqual(result.hit_type, "exact")
        self.assertEqual(result.answer, "The OnePlus Bullets are a good pick.")

    def test_exact_cache_miss_for_different_session(self):
        self.cache.set("cheap earbuds", "s1", "answer")
        self.assertIsNone(self.cache.get_exact("cheap earbuds", "s2"))

    def test_exact_cache_key_gets_a_positive_ttl(self):
        self.cache.set("cheap earbuds", "s1", "answer")
        key = f"rag:exact:{cache_key('cheap earbuds', 's1')}"
        self.assertGreater(self.redis.ttl(key), 0)

    def test_semantic_cache_hit_above_threshold(self):
        self.cache.set("cheap earbuds", "s1", "answer", query_embedding=[1.0, 0.0, 0.0])
        result = self.cache.get_semantic([1.0, 0.0, 0.0], "s1")
        self.assertIsNotNone(result)
        self.assertEqual(result.hit_type, "semantic")

    def test_semantic_cache_miss_below_threshold(self):
        self.cache.set("cheap earbuds", "s1", "answer", query_embedding=[1.0, 0.0, 0.0])
        result = self.cache.get_semantic([0.0, 1.0, 0.0], "s1")
        self.assertIsNone(result)

    def test_semantic_cache_scoped_to_session(self):
        self.cache.set("cheap earbuds", "s1", "answer", query_embedding=[1.0, 0.0, 0.0])
        result = self.cache.get_semantic([1.0, 0.0, 0.0], "s2")
        self.assertIsNone(result)


class RateLimiterRedisTests(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.limiter = _make_rate_limiter(self.redis, limit=3, window=60)

    def test_allows_up_to_limit(self):
        for _ in range(3):
            self.assertTrue(self.limiter.allow("user-1"))

    def test_blocks_after_limit_exceeded(self):
        for _ in range(3):
            self.limiter.allow("user-1")
        self.assertFalse(self.limiter.allow("user-1"))

    def test_separate_identities_tracked_independently(self):
        for _ in range(3):
            self.limiter.allow("user-1")
        self.assertTrue(self.limiter.allow("user-2"))

    def test_sets_expiry_on_first_hit(self):
        self.limiter.allow("user-1")
        self.assertGreater(self.redis.ttl("rag:rate:user-1"), 0)


class SessionStoreRedisTests(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.store = _make_session_store(self.redis, max_turns=20, ttl_seconds=86400)

    def test_append_and_get_recent_round_trip(self):
        self.store.append("s1", "hi", "hello")
        self.store.append("s1", "cheap earbuds?", "OnePlus Bullets are a good pick.")

        history = self.store.get_recent("s1", limit=4)

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0], {"user": "hi", "assistant": "hello"})
        self.assertEqual(history[1]["user"], "cheap earbuds?")

    def test_get_recent_respects_limit(self):
        for i in range(6):
            self.store.append("s1", f"q{i}", f"a{i}")

        history = self.store.get_recent("s1", limit=4)

        self.assertEqual([turn["user"] for turn in history], ["q2", "q3", "q4", "q5"])

    def test_truncates_stored_history_to_max_turns(self):
        self.store.max_turns = 3
        for i in range(5):
            self.store.append("s1", f"q{i}", f"a{i}")

        full_history = self.store.get_recent("s1", limit=100)

        self.assertEqual([turn["user"] for turn in full_history], ["q2", "q3", "q4"])

    def test_sessions_are_isolated(self):
        self.store.append("s1", "q1", "a1")
        self.store.append("s2", "q2", "a2")

        self.assertEqual(len(self.store.get_recent("s1")), 1)
        self.assertEqual(len(self.store.get_recent("s2")), 1)

    def test_sets_expiry_on_append(self):
        self.store.append("s1", "hi", "hello")
        self.assertGreater(self.redis.ttl("rag:session:s1"), 0)

    def test_unknown_session_returns_empty(self):
        self.assertEqual(self.store.get_recent("never-seen"), [])


class SessionStoreMemoryFallbackTests(unittest.TestCase):
    """Same behavior, no Redis -- exercises the in-memory fallback path
    that's actually been running this whole time in local dev."""

    def setUp(self):
        self.store = _make_session_store(None, max_turns=3, ttl_seconds=86400)

    def test_round_trip_and_truncation_without_redis(self):
        for i in range(5):
            self.store.append("s1", f"q{i}", f"a{i}")

        history = self.store.get_recent("s1", limit=100)

        self.assertEqual([turn["user"] for turn in history], ["q2", "q3", "q4"])


class RedisClientFallbackTests(unittest.TestCase):
    """_build_redis_client is shared by ResponseCache/RateLimiter/
    SessionStore -- covering it once here covers the fallback-on-failure
    guarantee for all three."""

    def setUp(self):
        self._original_redis_url = os.environ.pop("REDIS_URL", None)

    def tearDown(self):
        if self._original_redis_url is not None:
            os.environ["REDIS_URL"] = self._original_redis_url
        else:
            os.environ.pop("REDIS_URL", None)

    def test_returns_none_when_redis_url_unset(self):
        self.assertIsNone(_build_redis_client("test"))

    def test_returns_none_when_redis_unreachable(self):
        os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0?socket_connect_timeout=1"
        self.assertIsNone(_build_redis_client("test"))


if __name__ == "__main__":
    unittest.main()
