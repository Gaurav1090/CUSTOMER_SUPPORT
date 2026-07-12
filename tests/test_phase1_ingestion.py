import unittest

from langchain_core.documents import Document

from data_ingestion.ingestion_pipeline import DataIngestion


class Phase1IngestionTests(unittest.TestCase):
    def test_chunk_documents_splits_and_preserves_metadata(self):
        ingestion = DataIngestion.__new__(DataIngestion)
        ingestion.config = {"ingestion": {"chunk_size": 120, "chunk_overlap": 20}}
        ingestion.chunk_size = 120
        ingestion.chunk_overlap = 20

        doc = Document(
            page_content="word " * 80,
            metadata={
                "product_name": "Demo",
                "product_rating": 4,
                "product_summary": "Great",
                "source_row": 3,
            },
        )

        chunks = ingestion.chunk_documents([doc])

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].metadata["product_name"], "Demo")
        self.assertEqual(chunks[0].metadata["source_row"], 3)
        self.assertIn("chunk_index", chunks[0].metadata)

    def test_document_id_is_stable_for_same_content(self):
        ingestion = DataIngestion.__new__(DataIngestion)
        doc_a = Document(page_content="same review", metadata={"source_row": 1})
        doc_b = Document(page_content="same review", metadata={"source_row": 1})

        self.assertEqual(ingestion.build_document_id(doc_a), ingestion.build_document_id(doc_b))


if __name__ == "__main__":
    unittest.main()
