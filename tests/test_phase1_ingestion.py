import unittest

import pandas as pd
from langchain_core.documents import Document

from data_ingestion.ingestion_pipeline import DataIngestion


class Phase1IngestionTests(unittest.TestCase):
    def test_documents_from_dataframe_embeds_product_context(self):
        ingestion = DataIngestion.__new__(DataIngestion)
        df = pd.DataFrame(
            [
                {
                    "product_title": "Boat Rockerz 235 v2",
                    "rating": 4,
                    "summary": "Great bass",
                    "review": "Sound quality is excellent for the price.",
                }
            ]
        )

        documents = ingestion._documents_from_dataframe(df, "demo.csv", "data/landing/demo.csv")

        self.assertEqual(len(documents), 1)
        page_content = documents[0].page_content
        self.assertIn("Boat Rockerz 235 v2", page_content)
        self.assertIn("Sound quality is excellent for the price.", page_content)
        # Metadata still carries the structured fields for the rating/price
        # filters in retriever/retrieval.py -- the fix adds product context
        # to page_content, it doesn't remove it from metadata.
        self.assertEqual(documents[0].metadata["product_name"], "Boat Rockerz 235 v2")

    def test_documents_from_dataframe_omits_missing_fields(self):
        ingestion = DataIngestion.__new__(DataIngestion)
        df = pd.DataFrame(
            [
                {
                    "product_title": "Generic Earbuds",
                    "rating": 3,
                    "summary": None,
                    "review": "Decent for the price.",
                }
            ]
        )

        documents = ingestion._documents_from_dataframe(df, "demo.csv", "data/landing/demo.csv")

        self.assertNotIn("nan", documents[0].page_content.lower())
        self.assertNotIn("Summary:", documents[0].page_content)
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
