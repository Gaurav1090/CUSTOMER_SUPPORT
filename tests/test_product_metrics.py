import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from evaluation.product_metrics import _resolution_status, compute_product_metrics, fetch_traces


def _trace(session_id, citation_check=None, groundedness_verdict=None, output="an answer", **extra_metadata):
    metadata = {"session_id": session_id, **extra_metadata}
    if citation_check is not None:
        metadata["citation_check"] = citation_check
    if groundedness_verdict is not None:
        metadata["groundedness_verdict"] = groundedness_verdict
    return {
        "input": {"session_id": session_id},
        "output": {"answer": output} if output is not None else None,
        "metadata": metadata,
        # The real traces list endpoint returns score IDs here, not full
        # score objects -- feedback is read via fetch_feedback_scores
        # instead, never from this field. Left populated in fixtures to
        # guard against a regression back to reading it directly.
        "scores": ["some-score-id"],
    }


def _feedback_score(value):
    return {"name": "user_feedback", "value": value}


class ResolutionStatusTests(unittest.TestCase):
    def test_passed_citation_and_groundedness_is_resolved(self):
        trace = _trace("s1", citation_check="passed", groundedness_verdict="passed")
        self.assertEqual(_resolution_status(trace), "resolved")

    def test_no_context_is_excluded(self):
        trace = _trace("s1", citation_check="skipped_no_context", output="Insufficient context...")
        self.assertEqual(_resolution_status(trace), "excluded")

    def test_fabricated_citation_is_excluded(self):
        trace = _trace("s1", citation_check="failed")
        self.assertEqual(_resolution_status(trace), "excluded")

    def test_failed_groundedness_is_excluded(self):
        trace = _trace("s1", citation_check="passed", groundedness_verdict="failed")
        self.assertEqual(_resolution_status(trace), "excluded")

    def test_no_output_and_no_metadata_is_errored(self):
        trace = _trace("s1", output=None)
        self.assertEqual(_resolution_status(trace), "errored")


class ComputeProductMetricsTests(unittest.TestCase):
    def test_aggregates_rates_and_active_users(self):
        traces = [
            _trace("s1", citation_check="passed", groundedness_verdict="passed"),
            _trace("s1", citation_check="passed", groundedness_verdict="passed"),
            _trace("s2", citation_check="skipped_no_context", output="Insufficient context..."),
            _trace("s3", output=None),
            _trace("s3", citation_check="passed", groundedness_verdict="passed"),
        ]
        feedback_scores = [_feedback_score(1), _feedback_score(0)]

        with patch("evaluation.product_metrics.fetch_traces", return_value=traces), patch(
            "evaluation.product_metrics.fetch_feedback_scores", return_value=feedback_scores
        ):
            metrics = compute_product_metrics(datetime.now(timezone.utc))

        self.assertEqual(metrics["total_requests"], 5)
        self.assertEqual(metrics["active_users"], 3)
        self.assertEqual(metrics["resolved_requests"], 3)
        self.assertEqual(metrics["excluded_requests"], 1)
        self.assertEqual(metrics["errored_requests"], 1)
        self.assertAlmostEqual(metrics["auto_resolution_rate"], 3 / 5)
        self.assertAlmostEqual(metrics["exclusion_rate"], 1 / 5)
        self.assertEqual(metrics["feedback_up"], 1)
        self.assertEqual(metrics["feedback_down"], 1)
        self.assertAlmostEqual(metrics["csat_proxy"], 0.5)

    def test_empty_window_returns_none_rates_not_a_crash(self):
        with patch("evaluation.product_metrics.fetch_traces", return_value=[]), patch(
            "evaluation.product_metrics.fetch_feedback_scores", return_value=[]
        ):
            metrics = compute_product_metrics(datetime.now(timezone.utc))

        self.assertEqual(metrics["total_requests"], 0)
        self.assertIsNone(metrics["auto_resolution_rate"])
        self.assertIsNone(metrics["exclusion_rate"])
        self.assertIsNone(metrics["csat_proxy"])


class FetchTracesPaginationTests(unittest.TestCase):
    def test_follows_totalpages_across_multiple_pages(self):
        page1 = MagicMock()
        page1.json.return_value = {
            "data": [_trace("s1")],
            "meta": {"page": 1, "totalPages": 2},
        }
        page2 = MagicMock()
        page2.json.return_value = {
            "data": [_trace("s2")],
            "meta": {"page": 2, "totalPages": 2},
        }

        with patch("evaluation.product_metrics.requests.get", side_effect=[page1, page2]) as mock_get, patch.dict(
            "os.environ", {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}
        ):
            traces = fetch_traces(datetime.now(timezone.utc))

        self.assertEqual(len(traces), 2)
        self.assertEqual(mock_get.call_count, 2)

    def test_raises_when_langfuse_keys_unset(self):
        # _langfuse_auth() calls load_dotenv() itself, which would silently
        # refill a cleared os.environ from this repo's real .env -- stub it
        # out so the test actually exercises the "keys genuinely unset" path.
        with patch("evaluation.product_metrics.load_dotenv"), patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(EnvironmentError):
                fetch_traces(datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
