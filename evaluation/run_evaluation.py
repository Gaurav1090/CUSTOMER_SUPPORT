import json
import logging
import os
import sys
from typing import List, Optional, Tuple

from evaluation.evaluator import RAGEvaluator
from evaluation.golden_test_set import load_golden_test_set
from main import _judge_groundedness, invoke_chain
from retriever.retrieval import Retriever

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DEFAULT_BASELINE_PATH = "evaluation/baseline_results.json"
# Allowed drop in mean_score vs. the stored baseline before CI fails the
# build. Empirically calibrated: two consecutive real runs of the same
# golden set (no code changes between them) swung mean_score by ~0.06
# purely from Groq sampling noise on the generation/judge calls. Set below
# that and the gate would fail CI on noise alone.
DEFAULT_REGRESSION_TOLERANCE = 0.15


def run_evaluation(
    output_file: str = "evaluation/results.json",
    baseline_file: str = DEFAULT_BASELINE_PATH,
    regression_tolerance: float = DEFAULT_REGRESSION_TOLERANCE,
    fail_on_regression: bool = True,
) -> dict:
    """Run full evaluation on the golden test set. Exits the process with a
    non-zero status if scores regress beyond `regression_tolerance` against
    `baseline_file`, so CI actually fails the build instead of silently
    uploading a worse results.json as if nothing happened."""
    # Wire the evaluator's fallback faithfulness metric to the real
    # production groundedness judge, so it measures the same grounding
    # mechanism actually running in prod rather than a bag-of-words proxy.
    evaluator = RAGEvaluator(groundedness_fn=_judge_groundedness)
    retriever = Retriever()
    test_set = load_golden_test_set()
    results = []

    for i, test_case in enumerate(test_set):
        question = test_case["question"]
        logger.info(f"Evaluating test case {i+1}/{len(test_set)}: {question}")

        chat_history = test_case.get("chat_history")
        expected_sources = test_case.get("expected_sources", [])
        expected_keywords = test_case.get("expected_answer_contains", [])
        expected_answer = test_case.get("expected_answer")

        try:
            retrieved_docs = retriever.call_retriever(question, chat_history=chat_history)
            answer = invoke_chain(question)

            eval_result = evaluator.evaluate_end_to_end(
                question=question,
                retrieved_docs=retrieved_docs,
                answer=answer,
                expected_sources=expected_sources,
                expected_answer_keywords=expected_keywords,
                expected_answer=expected_answer,
            )
            eval_result["category"] = test_case.get("category")
            eval_result["retrieved_count"] = len(retrieved_docs)
            eval_result["answer_length"] = len(answer)
            results.append(eval_result)

            logger.info(f"  Overall score: {eval_result['overall_score']:.3f}")
        except Exception as exc:
            logger.exception(f"Error evaluating test case: {question}")
            results.append(
                {
                    "question": question,
                    "category": test_case.get("category"),
                    "error": str(exc),
                    "overall_score": 0.0,
                }
            )

    overall_stats = compute_stats(results)
    logger.info("\nOverall Statistics:")
    logger.info(f"  Mean score: {overall_stats['mean_score']:.3f}")
    logger.info(f"  Min score: {overall_stats['min_score']:.3f}")
    logger.info(f"  Max score: {overall_stats['max_score']:.3f}")

    output = {
        "test_set_size": len(test_set),
        "results": results,
        "statistics": overall_stats,
    }
    save_results(output, output_file)

    regressed, reason = check_regression(overall_stats, baseline_file, regression_tolerance)
    if regressed:
        logger.error("RAG quality regression detected: %s", reason)
        if fail_on_regression:
            sys.exit(1)

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


def check_regression(stats: dict, baseline_file: str, tolerance: float) -> Tuple[bool, Optional[str]]:
    """Compare mean_score against a stored baseline. No baseline file yet
    (e.g. the very first run) means there's nothing to regress against."""
    if not os.path.exists(baseline_file):
        logger.info("No baseline at %s; skipping regression check.", baseline_file)
        return False, None

    with open(baseline_file, "r", encoding="utf-8") as handle:
        baseline = json.load(handle)

    baseline_mean = baseline.get("statistics", {}).get("mean_score", 0.0)
    current_mean = stats.get("mean_score", 0.0)
    drop = baseline_mean - current_mean
    if drop > tolerance:
        return True, f"mean_score dropped from {baseline_mean:.3f} to {current_mean:.3f} (tolerance {tolerance:.3f})"
    return False, None


def save_results(output: dict, output_file: str) -> None:
    """Save evaluation results to JSON."""
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
    logger.info(f"Results saved to {output_file}")


if __name__ == "__main__":
    run_evaluation()
