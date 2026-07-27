import logging
from typing import Any, Callable, Dict, List, Optional

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

RAGAS_METRICS = []


class RAGEvaluator:
    """RAG evaluation. Uses RAGAS when installed and a real reference
    answer is supplied; otherwise falls back to lightweight metrics that
    need no extra dependency."""

    def __init__(self, groundedness_fn: Optional[Callable[[str, str], bool]] = None):
        self.ragas_available = self._try_import_ragas()
        # Optional callable(context, answer) -> bool, wired to the actual
        # production groundedness judge (main._judge_groundedness) by
        # evaluation/run_evaluation.py so the fallback faithfulness metric
        # exercises the same grounding mechanism running in prod, not a
        # weaker proxy. Unit tests omit it and get the fast token-overlap
        # fallback below so they don't need live LLM credentials.
        self.groundedness_fn = groundedness_fn

    def _try_import_ragas(self) -> bool:
        try:
            import ragas
            from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness, answer_correctness
            global RAGAS_METRICS
            RAGAS_METRICS = [context_precision, context_recall, faithfulness, answer_relevancy, answer_correctness]
            return True
        except ImportError:
            logger.warning("RAGAS not installed; using lightweight fallback metrics.")
            return False

    # ---------------------------------------------------------- retrieval

    def evaluate_retrieval(
        self,
        question: str,
        retrieved_docs: List[Document],
        expected_source_ids: List[str],
        expected_answer: Optional[str] = None,
    ) -> Dict[str, Any]:
        """context_precision/context_recall (unordered set overlap against
        expected_source_ids) plus MRR (rank-aware -- set overlap alone
        can't tell a relevant doc at position 1 from one buried at position
        10). Uses RAGAS's context_precision/context_recall instead when
        available and a real expected_answer is supplied -- RAGAS needs an
        actual reference answer as ground_truth, not a list of source ids."""
        if self.ragas_available and expected_answer:
            try:
                return self._evaluate_retrieval_ragas(question, retrieved_docs, expected_source_ids, expected_answer)
            except Exception:
                logger.exception("RAGAS retrieval evaluation failed; falling back to lightweight metrics.")

        return self._evaluate_retrieval_fallback(retrieved_docs, expected_source_ids)

    def _evaluate_retrieval_ragas(
        self, question: str, retrieved_docs: List[Document], expected_source_ids: List[str], expected_answer: str
    ) -> Dict[str, Any]:
        from ragas import evaluate
        from datasets import Dataset

        dataset = Dataset.from_dict(
            {
                "question": [question],
                "contexts": [[doc.page_content for doc in retrieved_docs]],
                "ground_truth": [expected_answer],
            }
        )
        metrics = [metric for metric in RAGAS_METRICS if metric.name in ("context_precision", "context_recall")]
        result_df = evaluate(dataset, metrics=metrics).to_pandas()
        return {
            "context_precision": float(result_df["context_precision"].mean()),
            "context_recall": float(result_df["context_recall"].mean()),
            "mrr": self._mean_reciprocal_rank(retrieved_docs, expected_source_ids),
            "retrieved_source_ids": [doc.metadata.get("source_id") for doc in retrieved_docs],
            "expected_source_ids": expected_source_ids,
        }

    def _evaluate_retrieval_fallback(self, retrieved_docs: List[Document], expected_source_ids: List[str]) -> Dict[str, Any]:
        retrieved_source_ids = {doc.metadata.get("source_id") for doc in retrieved_docs}
        expected_sources = set(expected_source_ids)
        mrr = self._mean_reciprocal_rank(retrieved_docs, expected_source_ids)

        if not expected_sources:
            return {"context_precision": 1.0, "context_recall": 1.0, "mrr": mrr}

        if not retrieved_source_ids:
            return {"context_precision": 0.0, "context_recall": 0.0, "mrr": mrr}

        true_positives = len(retrieved_source_ids.intersection(expected_sources))
        precision = true_positives / len(retrieved_source_ids) if retrieved_source_ids else 0.0
        recall = true_positives / len(expected_sources) if expected_sources else 0.0

        return {
            "context_precision": precision,
            "context_recall": recall,
            "mrr": mrr,
            "retrieved_source_ids": list(retrieved_source_ids),
            "expected_source_ids": expected_source_ids,
        }

    @staticmethod
    def _mean_reciprocal_rank(retrieved_docs: List[Document], expected_source_ids: List[str]) -> float:
        expected = set(expected_source_ids)
        if not expected:
            return 1.0
        for rank, doc in enumerate(retrieved_docs, start=1):
            if doc.metadata.get("source_id") in expected:
                return 1.0 / rank
        return 0.0

    # --------------------------------------------------------- generation

    def evaluate_generation(
        self,
        question: str,
        answer: str,
        context: str,
        expected_answer_contains: List[str],
        expected_answer: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.ragas_available and expected_answer:
            try:
                return self._evaluate_generation_ragas(question, answer, context, expected_answer)
            except Exception:
                logger.exception("RAGAS generation evaluation failed; falling back to lightweight metrics.")

        return self._evaluate_generation_fallback(question, answer, context, expected_answer_contains)

    def _evaluate_generation_ragas(self, question: str, answer: str, context: str, expected_answer: str) -> Dict[str, Any]:
        from ragas import evaluate
        from datasets import Dataset

        dataset = Dataset.from_dict(
            {
                "question": [question],
                "answer": [answer],
                "contexts": [[context]],
                "ground_truth": [expected_answer],
            }
        )
        metrics = [metric for metric in RAGAS_METRICS if metric.name in ("faithfulness", "answer_relevancy", "answer_correctness")]
        result_df = evaluate(dataset, metrics=metrics).to_pandas()
        return {
            "faithfulness": float(result_df["faithfulness"].mean()),
            "answer_relevance": float(result_df["answer_relevancy"].mean()),
        }

    def _evaluate_generation_fallback(
        self, question: str, answer: str, context: str, expected_answer_contains: List[str]
    ) -> Dict[str, Any]:
        if self.groundedness_fn is not None:
            try:
                faithfulness_score = 1.0 if self.groundedness_fn(context, answer) else 0.0
            except Exception:
                logger.exception("groundedness_fn failed; falling back to token-overlap faithfulness.")
                faithfulness_score = self._measure_faithfulness(answer, context)
        else:
            faithfulness_score = self._measure_faithfulness(answer, context)

        relevance_score = self._measure_relevance(answer, question, expected_answer_contains)

        return {
            "faithfulness": faithfulness_score,
            "answer_relevance": relevance_score,
            "expected_keywords": expected_answer_contains,
        }

    def _measure_faithfulness(self, answer: str, context: str) -> float:
        answer_lower = answer.lower()
        context_lower = context.lower()

        answer_tokens = set(answer_lower.split())
        context_tokens = set(context_lower.split())

        overlap = len(answer_tokens.intersection(context_tokens))
        if not answer_tokens:
            return 1.0
        score = overlap / len(answer_tokens)
        return min(1.0, max(0.0, score))

    def _measure_relevance(self, answer: str, question: str, expected_keywords: List[str]) -> float:
        answer_lower = answer.lower()
        matched_keywords = sum(1 for keyword in expected_keywords if keyword.lower() in answer_lower)
        if not expected_keywords:
            return 1.0
        return matched_keywords / len(expected_keywords)

    # -------------------------------------------------------- end-to-end

    def evaluate_end_to_end(
        self,
        question: str,
        retrieved_docs: List[Document],
        answer: str,
        expected_sources: List[str],
        expected_answer_keywords: List[str],
        expected_answer: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a full evaluation pipeline on a single query."""
        context_text = "\n\n".join(doc.page_content for doc in retrieved_docs)
        retrieval_metrics = self.evaluate_retrieval(question, retrieved_docs, expected_sources, expected_answer=expected_answer)
        generation_metrics = self.evaluate_generation(
            question, answer, context_text, expected_answer_keywords, expected_answer=expected_answer
        )

        return {
            "question": question,
            "retrieval": retrieval_metrics,
            "generation": generation_metrics,
            "overall_score": (
                retrieval_metrics["context_precision"] * 0.3
                + retrieval_metrics["context_recall"] * 0.2
                + generation_metrics["faithfulness"] * 0.25
                + generation_metrics["answer_relevance"] * 0.25
            ),
        }
