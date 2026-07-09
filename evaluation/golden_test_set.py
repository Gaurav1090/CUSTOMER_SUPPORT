import json
import os

GOLDEN_TEST_SET = [
    {
        "question": "Can you recommend a good budget headphone?",
        "expected_answer_contains": ["budget", "headphone"],
        "expected_sources": ["row-246", "row-250"],
        "context_rating_threshold": 4,
    },
    {
        "question": "What are the best earbuds under 2000?",
        "expected_answer_contains": ["budget", "earbuds", "2000"],
        "expected_sources": ["row-246", "row-250"],
        "context_rating_threshold": 4,
    },
    {
        "question": "Tell me about wireless headsets with good battery life.",
        "expected_answer_contains": ["wireless", "battery", "headset"],
        "expected_sources": ["row-246"],
        "context_rating_threshold": 3,
    },
]


def load_golden_test_set(custom_path: str = None) -> list:
    if custom_path and os.path.exists(custom_path):
        with open(custom_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return GOLDEN_TEST_SET


def save_golden_test_set(test_set: list, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(test_set, handle, indent=2)
