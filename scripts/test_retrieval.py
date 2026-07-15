"""Live retrieval smoke test -- run this against your real Chroma Cloud
collection and BM25 index (whatever's already been ingested) to sanity-check
each stage of the hybrid pipeline, not just the final merged output.

Usage:
    python scripts/test_retrieval.py
    python scripts/test_retrieval.py "your own query here"
"""
import sys

from retriever.retrieval import Retriever


DEFAULT_QUERIES = [
    # Plain semantic query -- exercises dense vector search.
    "What is the return policy?",
    # Exact phrase likely to appear verbatim -- exercises BM25 keyword search
    # pulling something dense search alone might rank lower.
    "warranty period",
    # Synonym expansion -- exercises rewrite_query (budget -> affordable/cheap).
    "cheap budget earbuds",
    # Metadata filter -- exercises parse_metadata_filters + apply_metadata_filters.
    "budget headphones rating>=4",
]


def describe(doc, index):
    metadata = doc.metadata or {}
    tag = metadata.get("source_id") or metadata.get("source_file") or "?"
    rating = metadata.get("product_rating")
    rating_str = f" (rating={rating})" if rating is not None else ""
    print(f"  {index}. [{tag}]{rating_str} {doc.page_content[:100]!r}")


def run_query(retriever: Retriever, query: str):
    print(f"\n{'=' * 70}\nQuery: {query!r}")

    rewritten = retriever.rewrite_query(query)
    if rewritten != query:
        print(f"Rewritten to: {rewritten!r}")

    filters = retriever.parse_metadata_filters(query)
    if filters:
        print(f"Parsed filters: {filters}")

    vector_retriever = retriever.load_retriever()
    dense = vector_retriever.invoke(rewritten)
    print(f"\nDense (vector) results: {len(dense)}")
    for i, doc in enumerate(dense, 1):
        describe(doc, i)

    sparse = retriever.keyword_search(rewritten, top_k=max(6, len(dense) * 2))
    print(f"\nSparse (BM25) results: {len(sparse)}")
    for i, doc in enumerate(sparse, 1):
        describe(doc, i)

    final = retriever.call_retriever(query)
    print(f"\nFinal (filtered + RRF merged + reranked, top {len(final)}):")
    for i, doc in enumerate(final, 1):
        describe(doc, i)


def main():
    retriever = Retriever()

    # Fail fast and clearly if the BM25 index is empty -- almost always
    # means ingestion hasn't been run yet, or INDEX_PATH doesn't match
    # what the ingestion job used.
    bm25 = retriever._load_bm25_index()
    print(f"BM25 index loaded from: {retriever.bm25_index_uri}")
    print(f"BM25 index size: {len(bm25.corpus_ids)} chunks")
    if not bm25.corpus_ids:
        print(
            "\nWARNING: BM25 index is empty. Either ingestion hasn't run "
            "yet, or INDEX_PATH here doesn't match the one ingestion used. "
            "Sparse/keyword results below will be empty until this is fixed."
        )

    queries = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_QUERIES
    for query in queries:
        run_query(retriever, query)


if __name__ == "__main__":
    main()
