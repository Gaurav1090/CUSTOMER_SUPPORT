# RAG Evaluation Framework

This directory contains the evaluation infrastructure for the RAG system, including:

1. **Golden Test Set** (`golden_test_set.py`): A curated set of customer questions with expected answers and sources.
2. **Evaluator** (`evaluator.py`): Lightweight RAGAS-style metrics for measuring retrieval and generation quality.
3. **Evaluation Runner** (`run_evaluation.py`): End-to-end evaluation pipeline that measures quality on the full test set.

## Metrics

- **Context Precision**: Of the retrieved documents, what fraction was relevant?
- **Context Recall**: Did we retrieve all the necessary documents?
- **Faithfulness**: Does the answer follow logically from the retrieved context?
- **Answer Relevance**: Does the answer address the user's question?

## Running Evaluations

### Local Evaluation
```bash
python evaluation/run_evaluation.py
# Results saved to evaluation/results.json
```

### CI Evaluation (GitHub Actions)
Evaluations are automatically triggered on every commit. See `.github/workflows/evaluation.yml` for configuration.

### Adding Custom Test Cases

Edit `evaluation/golden_test_set.py` to add new test cases:
```python
{
    "question": "Your question here",
    "expected_answer_contains": ["keyword1", "keyword2"],
    "expected_sources": ["row-1", "row-2"],
    "context_rating_threshold": 4,
}
```

## Quality Gates

The CI pipeline enforces minimum quality thresholds:
- **Average Retrieval Precision**: ≥ 0.0 (placeholder while test set grows)
- **Average Overall Score**: ≥ 0.4 on sample test cases

Adjust these in `tests/test_phase4_ci.py` as needed.

## Future Improvements

- Integrate RAGAS library for more sophisticated metrics
- Add semantic similarity scoring for answer validation
- Set up automated retraining when metrics fall below thresholds
- Export evaluation results to monitoring dashboard
