import unittest
from unittest.mock import patch

from langchain_core.documents import Document

from retriever.retrieval import Retriever


def make_retriever() -> Retriever:
    """Build a Retriever without hitting Chroma Cloud, env vars, or disk --
    __init__ normally loads config/env, which we don't need for pure logic
    tests on filters/rewrite/merge/rerank. Stub the reranker/rewrite-LLM
    state __init__ would normally set, so call_retriever exercises the
    lexical fallback path deterministically instead of trying to reach
    Cohere/Groq."""
    retriever = Retriever.__new__(Retriever)
    retriever.cohere_api_key = None
    retriever._reranker = None
    retriever._rewrite_llm = None
    retriever.last_standalone_query = None
    return retriever


class MetadataFilterParsingTests(unittest.TestCase):
    def setUp(self):
        self.retriever = make_retriever()

    def test_rating_gte_parsed_as_numeric(self):
        filters = self.retriever.parse_metadata_filters("budget laptops rating>=4")
        self.assertEqual(filters["product_rating"], {">=": 4.0})

    def test_multiple_filters_parsed_together(self):
        filters = self.retriever.parse_metadata_filters("category:electronics price<=500")
        self.assertEqual(filters["category"], {"contains": "electronics"})
        self.assertEqual(filters["price"], {"<=": 500.0})

    def test_no_filters_in_plain_query(self):
        filters = self.retriever.parse_metadata_filters("what is the return policy")
        self.assertEqual(filters, {})


class MetadataFilterApplicationTests(unittest.TestCase):
    def setUp(self):
        self.retriever = make_retriever()
        self.docs = [
            Document(page_content="great earbuds", metadata={"product_rating": 4.5}),
            Document(page_content="okay earbuds", metadata={"product_rating": 3.0}),
            Document(page_content="no rating on this one", metadata={}),
        ]

    def test_filters_out_below_threshold_and_missing_field(self):
        filters = {"product_rating": {">=": 4.0}}
        kept = self.retriever.apply_metadata_filters(self.docs, filters)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].page_content, "great earbuds")

    def test_no_filters_returns_everything_unchanged(self):
        kept = self.retriever.apply_metadata_filters(self.docs, {})
        self.assertEqual(kept, self.docs)


class QueryRewriteTests(unittest.TestCase):
    def setUp(self):
        self.retriever = make_retriever()

    def test_budget_synonym_expansion(self):
        rewritten = self.retriever.rewrite_query("cheap headphones")
        self.assertIn("affordable", rewritten)
        self.assertIn("earbuds", rewritten)


class RRFMergeTests(unittest.TestCase):
    def setUp(self):
        self.retriever = make_retriever()

    def test_doc_ranked_high_in_both_lists_wins(self):
        shared = Document(page_content="shared hit", metadata={"source_id": "shared"})
        dense_only = Document(page_content="dense only", metadata={"source_id": "dense"})
        sparse_only = Document(page_content="sparse only", metadata={"source_id": "sparse"})

        dense_results = [shared, dense_only]
        sparse_results = [shared, sparse_only]

        merged = self.retriever.rrf_merge(dense_results, sparse_results)
        self.assertEqual(merged[0].metadata["source_id"], "shared")
        self.assertEqual({d.metadata["source_id"] for d in merged}, {"shared", "dense", "sparse"})


class RerankTests(unittest.TestCase):
    def setUp(self):
        self.retriever = make_retriever()

    def test_higher_term_overlap_ranks_first(self):
        docs = [
            Document(page_content="totally unrelated content about shipping", metadata={}),
            Document(page_content="budget wireless earbuds battery life", metadata={}),
        ]
        reranked = self.retriever.rerank_documents(docs, "budget wireless earbuds", {})
        self.assertEqual(reranked[0].page_content, "budget wireless earbuds battery life")


class RerankSelectionTests(unittest.TestCase):
    """Covers _rerank's dispatch between semantic (Cohere) and lexical
    fallback reranking -- without a real Cohere API call, by stubbing
    _rerank_with_cohere the same way other tests stub load_retriever /
    keyword_search."""

    def setUp(self):
        self.retriever = make_retriever()
        self.retriever.config = {"retriever": {"rerank_top_k": 2}}
        self.docs = [
            Document(page_content="totally unrelated content about shipping", metadata={"source_id": "d1"}),
            Document(page_content="budget wireless earbuds battery life", metadata={"source_id": "d2"}),
        ]

    def test_empty_documents_returns_empty(self):
        self.retriever.cohere_api_key = "fake-key"
        self.assertEqual(self.retriever._rerank([], "query", {}), [])

    def test_uses_lexical_fallback_when_no_cohere_key(self):
        self.retriever.cohere_api_key = None
        result = self.retriever._rerank(self.docs, "budget wireless earbuds", {})
        self.assertEqual(result[0].metadata["source_id"], "d2")

    def test_uses_cohere_result_when_key_present(self):
        self.retriever.cohere_api_key = "fake-key"
        cohere_doc = Document(
            page_content="budget wireless earbuds battery life",
            metadata={"source_id": "d2", "relevance_score": 0.9},
        )
        self.retriever._rerank_with_cohere = lambda documents, query, top_n: [cohere_doc]

        result = self.retriever._rerank(self.docs, "budget wireless earbuds", {})

        self.assertEqual(result, [cohere_doc])

    def test_falls_back_to_lexical_when_cohere_call_fails(self):
        self.retriever.cohere_api_key = "fake-key"

        def _boom(documents, query, top_n):
            raise RuntimeError("cohere api down")

        self.retriever._rerank_with_cohere = _boom

        result = self.retriever._rerank(self.docs, "budget wireless earbuds", {})

        self.assertEqual(result[0].metadata["source_id"], "d2")


class HybridCallRetrieverTests(unittest.TestCase):
    """Exercises the full call_retriever pipeline (rewrite -> dense search ->
    keyword search -> filter -> RRF merge -> rerank -> dynamic top_k) with
    the two live dependencies (Chroma, BM25 index) faked out."""

    def setUp(self):
        self.retriever = make_retriever()
        self.retriever.config = {"retriever": {"top_k": 5}}

        self.dense_docs = [
            Document(page_content="Budget earbuds with 20hr battery", metadata={"source_id": "d1", "product_rating": 4.2}),
            Document(page_content="Premium noise cancelling headphones", metadata={"source_id": "d2", "product_rating": 4.8}),
        ]
        self.sparse_docs = [
            Document(page_content="Budget earbuds with 20hr battery", metadata={"source_id": "d1", "product_rating": 4.2}),
            Document(page_content="Cheap wired earphones for gym", metadata={"source_id": "d3", "product_rating": 3.1}),
        ]

        fake_vector_retriever = type(
            "FakeVectorRetriever", (), {"invoke": lambda self_, query: self.dense_docs}
        )()
        self.retriever.load_retriever = lambda: fake_vector_retriever
        self.retriever.keyword_search = lambda query, top_k=5: self.sparse_docs

    def test_hybrid_merge_returns_union_of_dense_and_sparse(self):
        results = self.retriever.call_retriever("budget earbuds")
        source_ids = {d.metadata["source_id"] for d in results}
        self.assertEqual(source_ids, {"d1", "d2", "d3"})

    def test_rating_filter_drops_non_matching_docs(self):
        results = self.retriever.call_retriever("budget earbuds rating>=4")
        source_ids = {d.metadata["source_id"] for d in results}
        # d3 (rating 3.1) should be filtered out by rating>=4
        self.assertNotIn("d3", source_ids)
        self.assertIn("d1", source_ids)


if __name__ == "__main__":
    unittest.main()
