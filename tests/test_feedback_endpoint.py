import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class FeedbackEndpointTests(unittest.TestCase):
    def setUp(self):
        main.app_api_key = "secret-key"
        self.client = TestClient(main.app)

    def test_requires_api_key(self):
        response = self.client.post("/feedback", json={"request_id": "r1", "rating": "up"})
        self.assertEqual(response.status_code, 401)

    def test_rejects_invalid_rating(self):
        response = self.client.post(
            "/feedback",
            json={"request_id": "r1", "rating": "sideways"},
            headers={"X-API-Key": "secret-key"},
        )
        self.assertEqual(response.status_code, 400)

    def test_records_valid_rating_and_reports_recorded_status(self):
        with patch("main.record_feedback_score", return_value=True) as mock_record:
            response = self.client.post(
                "/feedback",
                json={"request_id": "req-123", "rating": "up"},
                headers={"X-API-Key": "secret-key"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"recorded": True})
        mock_record.assert_called_once_with("req-123", "up")

    def test_reports_recorded_false_when_langfuse_unavailable(self):
        """Langfuse being down/unconfigured must not turn into a 5xx --
        the chat itself must keep working regardless of feedback."""
        with patch("main.record_feedback_score", return_value=False):
            response = self.client.post(
                "/feedback",
                json={"request_id": "req-123", "rating": "down"},
                headers={"X-API-Key": "secret-key"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"recorded": False})


if __name__ == "__main__":
    unittest.main()
