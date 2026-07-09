import unittest

from main import strip_reasoning_tokens


class Phase3GroundingTests(unittest.TestCase):
    def test_strip_reasoning_tokens_removes_reasoning_blocks(self):
        text = "Final answer<think>hidden</think> here"
        self.assertEqual(strip_reasoning_tokens(text), "Final answer here")

    def test_grounding_prompt_requires_citations_and_fallback(self):
        from prompt_library.prompt import PROMPT_TEMPLATES
        prompt = PROMPT_TEMPLATES["product_bot"]
        self.assertIn("citation", prompt.lower())
        self.assertIn("insufficient context", prompt.lower())


if __name__ == "__main__":
    unittest.main()
