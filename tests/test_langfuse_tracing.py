import unittest

from utils.ops import RequestTrace, build_langfuse_trace, finish_langfuse_trace


class _FakeSpan:
    """Records calls instead of talking to a real Langfuse client, so these
    tests exercise finish_langfuse_trace's logic without needing the
    (optional, not always installed) langfuse package or network access."""

    def __init__(self):
        self.update_calls = []
        self.score_calls = []
        self.ended = False

    def update(self, **kwargs):
        self.update_calls.append(kwargs)

    def score(self, **kwargs):
        self.score_calls.append(kwargs)

    def end(self):
        self.ended = True


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


if __name__ == "__main__":
    unittest.main()
