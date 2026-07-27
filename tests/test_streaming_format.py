import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


def _parse_sse_tokens(raw_body: str) -> str:
    """Mirrors templates/chat.html's own SSE parser: split on blank lines
    for event boundaries, then reassemble each "token" event's JSON-encoded
    payload. Used to prove the wire format the frontend actually consumes
    survives an embedded newline, not just that the endpoint returns 200."""
    reconstructed = ""
    for event_text in raw_body.split("\n\n"):
        lines = event_text.split("\n")
        event_name = ""
        data_line = ""
        for line in lines:
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            if line.startswith("data: "):
                data_line = line[len("data: "):]
        if event_name == "token" and data_line:
            reconstructed += json.loads(data_line)
    return reconstructed


class StreamingFormatTests(unittest.TestCase):
    def setUp(self):
        main.app_api_key = "secret-key"
        self.client = TestClient(main.app)

    def test_multiline_markdown_answer_survives_sse_round_trip(self):
        """Regression test: a naive f"data: {token}\\n\\n" per token
        silently truncated everything after the first embedded newline,
        because SSE requires each physical line of a "data:" field to carry
        its own "data:" prefix. Invisible until answers actually contained
        multi-line Markdown (headings/lists/tables) -- exactly what
        prompt_library/prompt.py's product_bot template now asks for."""
        markdown_answer = (
            "### Pros\n"
            "* Great bass [source:row-1]\n"
            "* Long battery life [source:row-2]\n\n"
            "| Product | Rating |\n"
            "| --- | --- |\n"
            "| Boat Rockerz | 4 |\n"
        )
        fake_result = {
            "answer": markdown_answer,
            "cache_hit": "miss",
            "retrieved_documents": [],
            "request_id": "test-request-id",
        }

        with patch("main.invoke_chain_details", return_value=fake_result):
            response = self.client.post(
                "/get/stream",
                data={"msg": "give me a formatted answer"},
                headers={"X-API-Key": "secret-key"},
            )

        self.assertEqual(response.status_code, 200)
        reconstructed = _parse_sse_tokens(response.text)
        self.assertEqual(reconstructed.strip(), markdown_answer.strip())


if __name__ == "__main__":
    unittest.main()
