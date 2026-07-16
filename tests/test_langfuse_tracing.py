import os
import unittest
from unittest.mock import patch

from utils.ops import (
    RequestTrace,
    build_langfuse_trace,
    finish_langfuse_trace,
    finish_llm_generation,
    record_feedback_score,
    start_llm_generation,
)


class _FakeGeneration:
    def __init__(self):
        self.update_calls = []
        self.ended = False

    def update(self, **kwargs):
        self.update_calls.append(kwargs)

    def end(self):
        self.ended = True


class _FakeSpan:
    """Records calls instead of talking to a real Langfuse client, so these
    tests exercise finish_langfuse_trace's logic without needing the
    (optional, not always installed) langfuse package or network access."""

    def __init__(self):
        self.update_calls = []
        self.score_calls = []
        self.ended = False
        self.started_observations = []

    def update(self, **kwargs):
        self.update_calls.append(kwargs)

    def score(self, **kwargs):
        self.score_calls.append(kwargs)

    def end(self):
        self.ended = True

    def start_observation(self, **kwargs):
        self.started_observations.append(kwargs)
        return _FakeGeneration()


class BuildLangfuseTraceTests(unittest.TestCase):
    def test_returns_none_when_keys_unset(self):
        import os

        os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        os.environ.pop("LANGFUSE_SECRET_KEY", None)
        trace = RequestTrace(request_id="r1", question="q", session_id="s1")
        self.assertIsNone(build_langfuse_trace(trace))


class FinishLangfuseTraceTests(unittest.TestCase):
    def setUp(self):
        self.trace = RequestTrace(request_id="r1", question="q", session_id="s1")

    def test_noop_when_span_is_none(self):
        # Must not raise -- this is the disabled/unconfigured path every
        # request takes by default.
        finish_langfuse_trace(None, self.trace, output="answer")

    def test_updates_and_ends_span_on_success(self):
        span = _FakeSpan()
        self.trace.add("citation_check", "passed")
        self.trace.add("groundedness_verdict", "passed")
        self.trace.add("cache_hit", "miss")

        finish_langfuse_trace(span, self.trace, output="the answer")

        self.assertEqual(len(span.update_calls), 1)
        update_kwargs = span.update_calls[0]
        self.assertEqual(update_kwargs["output"], {"answer": "the answer"})
        self.assertEqual(update_kwargs["metadata"]["cache_hit"], "miss")
        self.assertEqual(update_kwargs["level"], "DEFAULT")
        self.assertTrue(span.ended)

    def test_records_boolean_scores_for_citation_and_groundedness(self):
        span = _FakeSpan()
        self.trace.add("citation_check", "passed")
        self.trace.add("groundedness_verdict", "failed")

        finish_langfuse_trace(span, self.trace, output="answer")

        scores = {call["name"]: call["value"] for call in span.score_calls}
        self.assertEqual(scores["citation_check"], 1.0)
        self.assertEqual(scores["groundedness"], 0.0)

    def test_skips_scoring_when_verdict_was_skipped(self):
        """citation_check/groundedness_verdict can be "skipped_no_context"
        or "skipped_citation_failed" -- those aren't pass/fail signal and
        shouldn't be recorded as a 0/1 score, or they'd silently corrupt
        the dashboard's pass-rate trend."""
        span = _FakeSpan()
        self.trace.add("citation_check", "skipped_no_context")
        self.trace.add("groundedness_verdict", "skipped_no_context")

        finish_langfuse_trace(span, self.trace, output="answer")

        self.assertEqual(span.score_calls, [])

    def test_marks_error_level_and_status_message(self):
        span = _FakeSpan()

        finish_langfuse_trace(span, self.trace, error="boom")

        update_kwargs = span.update_calls[0]
        self.assertEqual(update_kwargs["level"], "ERROR")
        self.assertEqual(update_kwargs["status_message"], "boom")
        self.assertTrue(span.ended)

    def test_swallows_exceptions_from_the_span_itself(self):
        class _BrokenSpan(_FakeSpan):
            def update(self, **kwargs):
                raise RuntimeError("langfuse is down")

        # Must not raise -- an observability backend hiccup must never
        # break the actual user-facing response.
        finish_langfuse_trace(_BrokenSpan(), self.trace, output="answer")


class LlmGenerationTrackingTests(unittest.TestCase):
    def test_start_returns_none_when_parent_span_is_none(self):
        self.assertIsNone(start_llm_generation(None, "answer_generation", "llama-3.3-70b"))

    def test_finish_is_noop_when_generation_is_none(self):
        # Must not raise -- this is the disabled/unconfigured path every
        # request takes by default.
        finish_llm_generation(None, "output text", {"input_tokens": 10, "output_tokens": 5})

    def test_start_creates_nested_generation_observation_with_model(self):
        span = _FakeSpan()

        start_llm_generation(span, "answer_generation", "llama-3.3-70b", input_data={"question": "q"})

        self.assertEqual(len(span.started_observations), 1)
        call = span.started_observations[0]
        self.assertEqual(call["as_type"], "generation")
        self.assertEqual(call["model"], "llama-3.3-70b")
        self.assertEqual(call["name"], "answer_generation")

    def test_finish_translates_langchain_usage_keys_to_langfuse_schema(self):
        generation = _FakeGeneration()

        finish_llm_generation(
            generation, "the answer", {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160}
        )

        self.assertEqual(len(generation.update_calls), 1)
        usage = generation.update_calls[0]["usage_details"]
        self.assertEqual(usage, {"input": 120, "output": 40, "total": 160})
        self.assertEqual(generation.update_calls[0]["output"], "the answer")
        self.assertTrue(generation.ended)

    def test_finish_handles_missing_usage_metadata(self):
        """Not every provider populates usage_metadata (e.g. some
        HuggingFace router responses) -- must record the output without
        usage_details rather than raising."""
        generation = _FakeGeneration()

        finish_llm_generation(generation, "the answer", None)

        self.assertIsNone(generation.update_calls[0]["usage_details"])
        self.assertTrue(generation.ended)

    def test_finish_swallows_exceptions_from_the_generation_itself(self):
        class _BrokenGeneration(_FakeGeneration):
            def update(self, **kwargs):
                raise RuntimeError("langfuse is down")

        # Must not raise -- an observability backend hiccup must never
        # break the actual LLM call it's wrapping.
        finish_llm_generation(_BrokenGeneration(), "answer", {"input_tokens": 1})


class _FakeLangfuseClient:
    def __init__(self):
        self.score_calls = []

    def create_trace_id(self, *, seed):
        return f"trace-for-{seed}"

    def create_score(self, **kwargs):
        self.score_calls.append(kwargs)


class RecordFeedbackScoreTests(unittest.TestCase):
    def setUp(self):
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-test"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-test"

    def tearDown(self):
        os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        os.environ.pop("LANGFUSE_SECRET_KEY", None)

    def test_returns_false_when_keys_unset(self):
        os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        os.environ.pop("LANGFUSE_SECRET_KEY", None)
        self.assertFalse(record_feedback_score("req-1", "up"))

    def test_records_thumbs_up_as_boolean_score_on_the_original_trace(self):
        client = _FakeLangfuseClient()
        with patch("utils.ops._get_langfuse_client", return_value=client):
            result = record_feedback_score("req-1", "up")

        self.assertTrue(result)
        self.assertEqual(len(client.score_calls), 1)
        call = client.score_calls[0]
        self.assertEqual(call["name"], "user_feedback")
        self.assertEqual(call["value"], 1.0)
        self.assertEqual(call["trace_id"], "trace-for-req-1")
        self.assertEqual(call["data_type"], "BOOLEAN")

    def test_records_thumbs_down_as_zero(self):
        client = _FakeLangfuseClient()
        with patch("utils.ops._get_langfuse_client", return_value=client):
            record_feedback_score("req-2", "down")

        self.assertEqual(client.score_calls[0]["value"], 0.0)

    def test_returns_false_when_client_is_unavailable(self):
        with patch("utils.ops._get_langfuse_client", return_value=None):
            self.assertFalse(record_feedback_score("req-1", "up"))

    def test_swallows_exceptions_from_the_client_itself(self):
        class _BrokenClient(_FakeLangfuseClient):
            def create_score(self, **kwargs):
                raise RuntimeError("langfuse is down")

        # Must not raise -- an observability backend hiccup must never
        # break the feedback endpoint's response to the user.
        with patch("utils.ops._get_langfuse_client", return_value=_BrokenClient()):
            self.assertFalse(record_feedback_score("req-1", "up"))


if __name__ == "__main__":
    unittest.main()
