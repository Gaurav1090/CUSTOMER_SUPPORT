import unittest

from langchain_core.documents import Document

from evaluation.evaluator import RAGEvaluator
from evaluation.golden_test_set import load_golden_test_set


class Phase4EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.evaluator = RAGEvaluator()

    def test_evaluate_retrieval_computes_precision_and_recall(self):
        question = "best headphones"
        retrieved = [
            Document(page_content="text1", metadata={"source_id": "row-1"}),
            Document(page_content="text2", metadata={"source_id": "row-2"}),
            Document(page_content="text3", metadata={"source_id": "row-3"}),
        ]
        expected = ["row-1", "row-2"]

        metrics = self.evaluator.evaluate_retrieval(question, retrieved, expected)

        self.assertAlmostEqual(metrics["context_precision"], 2.0 / 3.0)
        self.assertEqual(metrics["context_recall"], 1.0)

    def test_evaluate_generation_measures_faithfulness_and_relevance(self):
        question = "best budget headphones"
        answer = "The budget headphones are great with good sound quality."
        context = "The budget headphones have good sound and long battery life."
        expected_keywords = ["budget", "headphones"]

        metrics = self.evaluator.evaluate_generation(question, answer, context, expected_keywords)

        self.assertGreater(metrics["faithfulness"], 0.5)
        self.assertGreater(metrics["answer_relevance"], 0.5)

    def test_evaluate_end_to_end_combines_retrieval_and_generation(self):
        question = "best budget headphones"
        retrieved = [
            Document(page_content="Budget earphones have great sound", metadata={"source_id": "row-1"}),
        ]
        answer = "The budget headphones offer excellent value."
        expected_sources = ["row-1"]
        expected_keywords = ["budget", "headphones"]

        result = self.evaluator.evaluate_end_to_end(
            question, retrieved, answer, expected_sources, expected_keywords
        )

        self.assertIn("overall_score", result)
        self.assertGreater(result["overall_score"], 0.0)

    def test_golden_test_set_loads_without_error(self):
        test_set = load_golden_test_set()
        self.assertGreater(len(test_set), 0)
        for test_case in test_set:
            self.assertIn("question", test_case)
            self.assertIn("expected_answer_contains", test_case)
            self.assertIn("expected_sources", test_case)

    def test_mrr_is_one_for_first_rank_hit(self):
        retrieved = [
            Document(page_content="text1", metadata={"source_id": "row-1"}),
            Document(page_content="text2", metadata={"source_id": "row-2"}),
        ]
        metrics = self.evaluator.evaluate_retrieval("q", retrieved, ["row-1"])
        self.assertEqual(metrics["mrr"], 1.0)

    def test_mrr_reflects_rank_position(self):
        retrieved = [
            Document(page_content="text1", metadata={"source_id": "row-1"}),
            Document(page_content="text2", metadata={"source_id": "row-2"}),
            Document(page_content="text3", metadata={"source_id": "row-3"}),
        ]
        metrics = self.evaluator.evaluate_retrieval("q", retrieved, ["row-3"])
        self.assertAlmostEqual(metrics["mrr"], 1.0 / 3.0)

    def test_mrr_is_zero_when_expected_source_not_retrieved(self):
        retrieved = [Document(page_content="text1", metadata={"source_id": "row-1"})]
        metrics = self.evaluator.evaluate_retrieval("q", retrieved, ["row-99"])
        self.assertEqual(metrics["mrr"], 0.0)


class GroundednessFnInjectionTests(unittest.TestCase):
    """The fallback faithfulness metric can be wired to the real production
    groundedness judge (main._judge_groundedness) instead of the bag-of-words
    heuristic -- evaluation/run_evaluation.py does this; here we verify the
    wiring and its failure fallback without needing a live LLM."""

    def test_uses_injected_groundedness_fn_when_true(self):
        evaluator = RAGEvaluator(groundedness_fn=lambda context, answer: True)
        metrics = evaluator.evaluate_generation("q", "some answer", "some context", [])
        self.assertEqual(metrics["faithfulness"], 1.0)

    def test_uses_injected_groundedness_fn_when_false(self):
        evaluator = RAGEvaluator(groundedness_fn=lambda context, answer: False)
        metrics = evaluator.evaluate_generation("q", "some answer", "some context", [])
        self.assertEqual(metrics["faithfulness"], 0.0)

    def test_recovers_when_groundedness_fn_raises(self):
        def _boom(context, answer):
            raise RuntimeError("llm down")

        evaluator = RAGEvaluator(groundedness_fn=_boom)
        metrics = evaluator.evaluate_generation(
            "best budget headphones",
            "The budget headphones are great.",
            "The budget headphones have good sound.",
            ["budget"],
        )
        self.assertIn("faithfulness", metrics)
        self.assertGreaterEqual(metrics["faithfulness"], 0.0)


if __name__ == "__main__":
    unittest.main()
