import unittest

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from retriever.query_rewriter import classify_comparison_products, contextualize_query


class ContextualizeQueryTests(unittest.TestCase):
    def test_skips_llm_call_when_no_prior_conversation(self):
        calls = []
        load_llm = lambda: calls.append("loaded") or RunnableLambda(
            lambda prompt_value: AIMessage(content="unused")
        )

        result = contextualize_query("cheap earbuds", "No prior conversation.", load_llm)

        self.assertEqual(result, "cheap earbuds")
        self.assertEqual(calls, [])

    def test_skips_llm_call_when_history_is_empty(self):
        load_llm = lambda: RunnableLambda(lambda prompt_value: AIMessage(content="unused"))

        result = contextualize_query("cheap earbuds", "", load_llm)

        self.assertEqual(result, "cheap earbuds")

    def test_rewrites_using_history(self):
        fake_llm = RunnableLambda(lambda prompt_value: AIMessage(content="premium wireless headphones with strong bass"))
        history = "User: What budget earbuds do you have?\nAssistant: The OnePlus Bullets Wireless Z is a good pick."

        result = contextualize_query("what about a more premium one?", history, lambda: fake_llm)

        self.assertEqual(result, "premium wireless headphones with strong bass")

    def test_falls_back_to_raw_question_on_invoke_failure(self):
        def _boom(_prompt_value):
            raise RuntimeError("groq is down")

        fake_llm = RunnableLambda(_boom)
        history = "User: hi\nAssistant: hello"

        result = contextualize_query("what about a cheaper one?", history, lambda: fake_llm)

        self.assertEqual(result, "what about a cheaper one?")

    def test_falls_back_to_raw_question_on_load_llm_failure(self):
        """Regression test: load_llm() raising (e.g. missing API key/token)
        must be caught the same as an invoke() failure -- it previously
        wasn't, because the caller evaluated the old eager `llm` argument
        before this function's try/except ever ran, so a load failure
        crashed retrieval entirely instead of falling back to the raw
        question."""
        def load_llm():
            raise RuntimeError("Missing environment variables: ['HF_TOKEN']")

        history = "User: hi\nAssistant: hello"

        result = contextualize_query("what about a cheaper one?", history, load_llm)

        self.assertEqual(result, "what about a cheaper one?")

    def test_empty_question_returned_unchanged(self):
        load_llm = lambda: RunnableLambda(lambda prompt_value: AIMessage(content="unused"))

        result = contextualize_query("", "some history", load_llm)

        self.assertEqual(result, "")


class ClassifyComparisonProductsTests(unittest.TestCase):
    def test_extracts_two_products_from_product_lines(self):
        fake_llm = RunnableLambda(
            lambda prompt_value: AIMessage(content="PRODUCT: Boat Rockerz 235v2\nPRODUCT: OnePlus Bullets Wireless Z")
        )

        result = classify_comparison_products(
            "How does the Boat Rockerz 235v2 compare to the OnePlus Bullets Wireless Z?", lambda: fake_llm
        )

        self.assertEqual(result, ["Boat Rockerz 235v2", "OnePlus Bullets Wireless Z"])

    def test_returns_none_for_single_product_question(self):
        fake_llm = RunnableLambda(lambda prompt_value: AIMessage(content="NONE"))

        result = classify_comparison_products("How is the Boat Rockerz 235v2?", lambda: fake_llm)

        self.assertIsNone(result)

    def test_returns_none_when_only_one_product_line_extracted(self):
        """A single PRODUCT: line isn't a comparison -- guards against a
        model partially following the format without actually naming two
        distinct products."""
        fake_llm = RunnableLambda(lambda prompt_value: AIMessage(content="PRODUCT: Boat Rockerz 235v2"))

        result = classify_comparison_products("How is the Boat Rockerz 235v2?", lambda: fake_llm)

        self.assertIsNone(result)

    def test_returns_none_on_invoke_failure(self):
        def _boom(_prompt_value):
            raise RuntimeError("groq is down")

        result = classify_comparison_products("compare A and B", lambda: RunnableLambda(_boom))

        self.assertIsNone(result)

    def test_returns_none_on_load_llm_failure(self):
        def load_llm():
            raise RuntimeError("Missing environment variables: ['GROQ_API_KEY']")

        result = classify_comparison_products("compare A and B", load_llm)

        self.assertIsNone(result)

    def test_empty_question_returns_none_without_llm_call(self):
        calls = []
        load_llm = lambda: calls.append("loaded") or RunnableLambda(lambda prompt_value: AIMessage(content="NONE"))

        result = classify_comparison_products("", load_llm)

        self.assertIsNone(result)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
