import unittest

from langchain_core.documents import Document

from retriever.retrieval import Retriever


class Phase2RetrievalTests(unittest.TestCase):
    def test_parse_metadata_filters_supports_numeric_and_text_filters(self):
        retriever = Retriever.__new__(Retriever)
        filters = retriever.parse_metadata_filters("find rating >= 4 and category:headphones")

        self.assertEqual(filters["product_rating"][">="], 4)
        self.assertEqual(filters["category"]["contains"], "headphones")

    def test_rewrite_query_expands_common_terms(self):
        retriever = Retriever.__new__(Retriever)
        rewritten = retriever.rewrite_query("budget headphone")

        self.assertIn("budget", rewritten)
        self.assertIn("headphones", rewritten)

    def test_rrf_merge_prefers_documents_present_in_multiple_sources(self):
        retriever = Retriever.__new__(Retriever)
        dense = [Document(page_content="alpha", metadata={"source_id": "a"}), Document(page_content="beta", metadata={"source_id": "b"})]
        sparse = [Document(page_content="alpha", metadata={"source_id": "a"}), Document(page_content="gamma", metadata={"source_id": "c"})]

        merged = retriever.rrf_merge(dense, sparse)

        self.assertEqual(merged[0].metadata["source_id"], "a")
        self.assertEqual(merged[1].metadata["source_id"], "b")


if __name__ == "__main__":
    unittest.main()
