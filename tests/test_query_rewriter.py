import unittest

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from retriever.query_rewriter import contextualize_query


class ContextualizeQueryTests(unittest.TestCase):
    def test_skips_llm_call_when_no_prior_conversation(self):
        calls = []
        fake_llm = RunnableLambda(lambda prompt_value: calls.append(prompt_value) or AIMessage(content="unused"))

        result = contextualize_query("cheap earbuds", "No prior conversation.", fake_llm)

        self.assertEqual(result, "cheap earbuds")
        self.assertEqual(calls, [])

    def test_skips_llm_call_when_history_is_empty(self):
        fake_llm = RunnableLambda(lambda prompt_value: AIMessage(content="unused"))

        result = contextualize_query("cheap earbuds", "", fake_llm)

        self.assertEqual(result, "cheap earbuds")

    def test_rewrites_using_history(self):
        fake_llm = RunnableLambda(lambda prompt_value: AIMessage(content="premium wireless headphones with strong bass"))
        history = "User: What budget earbuds do you have?\nAssistant: The OnePlus Bullets Wireless Z is a good pick."

        result = contextualize_query("what about a more premium one?", history, fake_llm)

        self.assertEqual(result, "premium wireless headphones with strong bass")

    def test_falls_back_to_raw_question_on_llm_failure(self):
        def _boom(_prompt_value):
            raise RuntimeError("groq is down")

        fake_llm = RunnableLambda(_boom)
        history = "User: hi\nAssistant: hello"

        result = contextualize_query("what about a cheaper one?", history, fake_llm)

        self.assertEqual(result, "what about a cheaper one?")

    def test_empty_question_returned_unchanged(self):
        fake_llm = RunnableLambda(lambda prompt_value: AIMessage(content="unused"))

        result = contextualize_query("", "some history", fake_llm)

        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
