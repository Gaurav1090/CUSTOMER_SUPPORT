import unittest

from fastapi.testclient import TestClient

import main


class Phase0SecurityTests(unittest.TestCase):
    def test_strip_reasoning_tokens_removes_think_blocks(self):
        raw = "Here is the answer<think>hidden reasoning</think> to show."
        self.assertEqual(main.strip_reasoning_tokens(raw), "Here is the answer to show.")

    def test_missing_api_key_is_rejected(self):
        main.app_api_key = "secret-key"
        client = TestClient(main.app)

        response = client.post("/get", data={"msg": "hello"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid or missing API key", response.text)

    def test_stream_endpoint_requires_api_key(self):
        main.app_api_key = "secret-key"
        client = TestClient(main.app)

        response = client.post("/get/stream", data={"msg": "hello"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid or missing API key", response.text)

    def test_health_endpoint_is_public(self):
        client = TestClient(main.app)

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")

    def test_ready_endpoint_reports_checks(self):
        client = TestClient(main.app)

        response = client.get("/ready")

        self.assertIn(response.status_code, {200, 503})
        self.assertIn("checks", response.json())


if __name__ == "__main__":
    unittest.main()
