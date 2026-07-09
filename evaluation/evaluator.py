import logging
from typing import Any, Dict, List

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class RAGEvaluator:
    """Lightweight RAG evaluation using available metrics."""

    def __init__(self):
        self.try_ragas = self._try_import_ragas()

    def _try_import_ragas(self) -> bool:
        try:
            import ragas
            from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
            self.ragas_available = True
            return True
        except ImportError:
            logger.warning("RAGAS not installed; using lightweight fallback metrics.")
            self.ragas_available = False
            return False

    def evaluate_retrieval(
        self,
        question: str,
        retrieved_docs: List[Document],
        expected_source_ids: List[str],
    ) -> Dict[str, Any]:
        """Evaluate retrieval quality using context precision and recall."""
        retrieved_source_ids = {doc.metadata.get("source_id") for doc in retrieved_docs}
        expected_sources = set(expected_source_ids)

        if not expected_sources:
            return {"context_precision": 1.0, "context_recall": 1.0}

        if not retrieved_source_ids:
            return {"context_precision": 0.0, "context_recall": 0.0}

        true_positives = len(retrieved_source_ids.intersection(expected_sources))
        precision = true_positives / len(retrieved_source_ids) if retrieved_source_ids else 0.0
        recall = true_positives / len(expected_sources) if expected_sources else 0.0

        return {
            "context_precision": precision,
            "context_recall": recall,
            "retrieved_source_ids": list(retrieved_source_ids),
            "expected_source_ids": expected_source_ids,
        }

    def evaluate_generation(
        self,
        question: str,
        answer: str,
        context: str,
        expected_answer_contains: List[str],
    ) -> Dict[str, Any]:
        """Evaluate generation quality using faithfulness and relevance."""
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

    def evaluate_end_to_end(
        self,
        question: str,
        retrieved_docs: List[Document],
        answer: str,
        expected_sources: List[str],
        expected_answer_keywords: List[str],
    ) -> Dict[str, Any]:
        """Run a full evaluation pipeline on a single query."""
        context_text = "\n\n".join(doc.page_content for doc in retrieved_docs)
        retrieval_metrics = self.evaluate_retrieval(question, retrieved_docs, expected_sources)
        generation_metrics = self.evaluate_generation(question, answer, context_text, expected_answer_keywords)

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
