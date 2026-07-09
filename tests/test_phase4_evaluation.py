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


if __name__ == "__main__":
    unittest.main()
