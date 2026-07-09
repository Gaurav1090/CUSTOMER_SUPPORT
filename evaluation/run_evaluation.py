import json
import logging
import os
from typing import List

from langchain_core.documents import Document

from evaluation.evaluator import RAGEvaluator
from evaluation.golden_test_set import load_golden_test_set
from main import invoke_chain
from retriever.retrieval import Retriever

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def run_evaluation(output_file: str = "evaluation/results.json") -> dict:
    """Run full evaluation on golden test set."""
    evaluator = RAGEvaluator()
    retriever = Retriever()
    test_set = load_golden_test_set()
    results = []

    for i, test_case in enumerate(test_set):
        logger.info(f"Evaluating test case {i+1}/{len(test_set)}: {test_case['question']}")

        question = test_case["question"]
        expected_sources = test_case.get("expected_sources", [])
        expected_keywords = test_case.get("expected_answer_contains", [])

        try:
            retrieved_docs = retriever.call_retriever(question)
            answer = invoke_chain(question)

            eval_result = evaluator.evaluate_end_to_end(
                question=question,
                retrieved_docs=retrieved_docs,
                answer=answer,
                expected_sources=expected_sources,
                expected_answer_keywords=expected_keywords,
            )
            eval_result["retrieved_count"] = len(retrieved_docs)
            eval_result["answer_length"] = len(answer)
            results.append(eval_result)

            logger.info(f"  Overall score: {eval_result['overall_score']:.3f}")
        except Exception as exc:
            logger.exception(f"Error evaluating test case: {question}")
            results.append({
                "question": question,
                "error": str(exc),
                "overall_score": 0.0,
            })

    overall_stats = compute_stats(results)
    logger.info(f"\nOverall Statistics:")
    logger.info(f"  Mean score: {overall_stats['mean_score']:.3f}")
    logger.info(f"  Min score: {overall_stats['min_score']:.3f}")
    logger.info(f"  Max score: {overall_stats['max_score']:.3f}")

    output = {
        "test_set_size": len(test_set),
        "results": results,
        "statistics": overall_stats,
    }
    save_results(output, output_file)
    return output


def compute_stats(results: List[dict]) -> dict:
    """Compute aggregate statistics."""
    scores = [r.get("overall_score", 0.0) for r in results]
    if not scores:
        return {"mean_score": 0.0, "min_score": 0.0, "max_score": 0.0}

    return {
        "mean_score": sum(scores) / len(scores),
        "min_score": min(scores),
        "max_score": max(scores),
        "passed": sum(1 for s in scores if s >= 0.7),
        "total": len(scores),
    }


def save_results(output: dict, output_file: str) -> None:
    """Save evaluation results to JSON."""
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
    logger.info(f"Results saved to {output_file}")


if __name__ == "__main__":
    run_evaluation()
