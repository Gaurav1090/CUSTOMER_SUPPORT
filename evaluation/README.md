# RAG Evaluation Framework

This directory contains the evaluation infrastructure for the RAG system, including:

1. **Golden Test Set** (`golden_test_set.py`): 12 labeled cases spanning
   recommendation, comparison, metadata-filter, out-of-scope, multi-turn, and
   prompt-injection-probe categories. `expected_sources` use the real
   ingestion `source_id` format (`<file>:row-N`); left empty for queries
   where a single "correct" source isn't well-defined (see the comment on
   the first two entries).
2. **Evaluator** (`evaluator.py`): Uses RAGAS metrics when installed and a
   real `expected_answer` is supplied per case, otherwise a lightweight
   fallback (token-overlap faithfulness, keyword-coverage relevance, set-based
   precision/recall). Always computes MRR (rank-aware, unlike precision/recall
   which only look at set overlap). The fallback faithfulness metric can be
   wired to the actual production groundedness judge (`main._judge_groundedness`)
   via `RAGEvaluator(groundedness_fn=...)` -- `run_evaluation.py` does this.
3. **Evaluation Runner** (`run_evaluation.py`): End-to-end evaluation pipeline
   that measures quality on the full test set and gates CI on regression
   against `baseline_results.json`.

## Metrics

- **Context Precision**: Of the retrieved documents, what fraction was relevant?
- **Context Recall**: Did we retrieve all the necessary documents?
- **MRR**: Reciprocal rank of the first relevant document -- unlike precision/
  recall, this is sensitive to *where* in the ranking a relevant doc landed.
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
    "category": "recommendation",  # informational, not read by any code
    "question": "Your question here",
    "expected_answer": "A real reference answer -- used as RAGAS's ground_truth.",
    "expected_answer_contains": ["keyword1", "keyword2"],
    "expected_sources": ["flipkart_product_review.csv:row-1"],  # match the real
                                                                  # source_id format,
                                                                  # or [] if there's no
                                                                  # single correct source
    "chat_history": None,  # optional: a pre-built history string for multi-turn cases
}
```

`expected_sources` must match the actual `source_id` format assigned during
ingestion (`data_ingestion/ingestion_pipeline.py`: `f"{source_file}:row-{index+1}"`)
-- a bare `"row-N"` will never match and silently zeroes out precision/recall/MRR
for that case.

## Quality Gates

- `tests/test_phase4_ci.py`: a live smoke test (real retriever + real LLM
  calls) asserting retrieval returns something and average score clears a
  minimum bar.
- `evaluation/run_evaluation.py`: the real gate. Compares `mean_score`
  against `evaluation/baseline_results.json` and exits non-zero if it drops
  by more than `DEFAULT_REGRESSION_TOLERANCE` (0.15 -- calibrated from
  observed run-to-run LLM sampling noise on the same golden set, ~0.06;
  anything tighter fails CI on noise alone). Regenerate the baseline
  deliberately (`cp evaluation/results.json evaluation/baseline_results.json`
  after a real run) when you intend to raise the quality bar.

## Possible next steps

- Expand the golden set further, especially metadata-filter cases (the
  bundled demo CSV only has a `rating` column that's actually filterable --
  `price`/`category`/`brand` filters exist in the retriever but never match
  anything in this dataset)
- Track per-category scores over time, not just one aggregate mean
- Export evaluation results to a monitoring dashboard
