import hashlib
import json
import os
import re
from typing import Any, List, Optional

import pandas as pd
from dotenv import load_dotenv
from langchain_core.documents import Document

from utils.chroma_utils import create_chroma_store
from utils.config_loader import load_config
from utils.model_loader import ModelLoader


class DataIngestion:
    """Handle transformation and ingestion of review data into a Chroma-based vector store."""

    def __init__(self):
        print("Initializing DataIngestion pipeline...")
        self.config = load_config()
        self.model_loader = ModelLoader()
        self._load_env_variables()
        self.csv_path = self._get_csv_path()
        self.product_data = self._load_csv()
        self.state_file = os.path.join(os.getcwd(), self.config.get("ingestion", {}).get("state_file", "data/.ingestion_state.json"))
        self.keyword_index_path = os.path.join(os.getcwd(), self.config.get("ingestion", {}).get("keyword_index_file", "data/.keyword_index.json"))
        self._ensure_state_files()

    def _load_env_variables(self):
        """Load optional environment variables used by the ingestion pipeline."""
        load_dotenv()

        required_vars = []
        if self.config["embedding_model"]["provider"] == "google":
            required_vars.append("GOOGLE_API_KEY")

        missing_vars = [var for var in required_vars if os.getenv(var) is None]
        if missing_vars:
            raise EnvironmentError(f"Missing environment variables: {missing_vars}")

        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        self.chroma_api_key = os.getenv("CHROMA_API_KEY")
        self.chroma_tenant = os.getenv("CHROMA_TENANT")
        self.chroma_database = os.getenv("CHROMA_DATABASE")

    def _get_csv_path(self):
        """Get path to the CSV file located inside the data folder."""
        current_dir = os.getcwd()
        csv_path = os.path.join(current_dir, "data", "flipkart_product_review.csv")

        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found at: {csv_path}")

        return csv_path

    def _load_csv(self):
        """Load product data from CSV."""
        df = pd.read_csv(self.csv_path)
        expected_columns = {"product_title", "rating", "summary", "review"}

        if not expected_columns.issubset(set(df.columns)):
            raise ValueError(f"CSV must contain columns: {expected_columns}")

        return df

    def _ensure_state_files(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.keyword_index_path), exist_ok=True)
        if not os.path.exists(self.state_file):
            with open(self.state_file, "w", encoding="utf-8") as handle:
                json.dump({"processed_ids": []}, handle)
        if not os.path.exists(self.keyword_index_path):
            with open(self.keyword_index_path, "w", encoding="utf-8") as handle:
                json.dump({}, handle)

    def _load_processed_ids(self) -> set[str]:
        try:
            with open(self.state_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return set(data.get("processed_ids", []))
        except (FileNotFoundError, json.JSONDecodeError):
            return set()

    def _save_processed_ids(self, ids: List[str]) -> None:
        existing_ids = self._load_processed_ids()
        existing_ids.update(ids)
        with open(self.state_file, "w", encoding="utf-8") as handle:
            json.dump({"processed_ids": sorted(existing_ids)}, handle)

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _write_keyword_index(self, documents: List[Document]) -> None:
        index: dict[str, dict[str, Any]] = {}
        for doc in documents:
            doc_id = self.build_document_id(doc)
            tokens = self._tokenize(doc.page_content or "")
            index[doc_id] = {
                "text": doc.page_content,
                "metadata": doc.metadata,
                "tokens": {token: tokens.count(token) for token in set(tokens)},
            }

        with open(self.keyword_index_path, "w", encoding="utf-8") as handle:
            json.dump(index, handle, indent=2)

    def build_document_id(self, document: Document) -> str:
        metadata = document.metadata or {}
        payload = {
            "content": document.page_content,
            "metadata": {key: metadata.get(key) for key in sorted(metadata.keys())},
        }
        content = json.dumps(payload, sort_keys=True, default=str)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        source_id = metadata.get("source_id") or "document"
        return f"{source_id}:{digest[:12]}"

    def _create_splitter(self):
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError:
            return None

        chunk_size = int(self.config.get("ingestion", {}).get("chunk_size", 400))
        chunk_overlap = int(self.config.get("ingestion", {}).get("chunk_overlap", 80))
        return RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def chunk_documents(self, documents: List[Document]) -> List[Document]:
        splitter = self._create_splitter()
        chunked_documents: List[Document] = []
        chunk_size = int(self.config.get("ingestion", {}).get("chunk_size", 400))
        chunk_overlap = int(self.config.get("ingestion", {}).get("chunk_overlap", 80))

        for document in documents:
            parent_metadata = dict(document.metadata or {})
            if splitter is not None:
                split_docs = splitter.split_documents([document])
            else:
                text = document.page_content or ""
                split_docs = []
                if text.strip():
                    start = 0
                    while start < len(text):
                        end = min(len(text), start + chunk_size)
                        chunk_text = text[start:end].strip()
                        if not chunk_text:
                            break
                        split_docs.append(Document(page_content=chunk_text, metadata=dict(parent_metadata)))
                        if end >= len(text):
                            break
                        start = max(0, end - chunk_overlap)

            if not split_docs:
                continue
            for index, chunk in enumerate(split_docs):
                metadata = dict(parent_metadata)
                metadata.update(
                    {
                        "chunk_index": index,
                        "chunk_count": len(split_docs),
                        "source_id": parent_metadata.get("source_id") or self.build_document_id(document),
                    }
                )
                chunk.metadata = metadata
                chunked_documents.append(chunk)

        return chunked_documents

    def transform_data(self):
        """Transform product data into chunked LangChain Document objects with structured metadata."""
        documents: List[Document] = []

        for index, row in self.product_data.iterrows():
            metadata: dict[str, Any] = {
                "product_name": row.get("product_title") if "product_title" in row.index else None,
                "product_rating": row.get("rating") if "rating" in row.index else None,
                "product_summary": row.get("summary") if "summary" in row.index else None,
                "source_row": int(index + 1),
                "source_file": os.path.basename(self.csv_path),
                "source_id": f"row-{index + 1}",
            }

            for optional_field in ("price", "category", "brand"):
                if optional_field in row.index:
                    metadata[optional_field] = row.get(optional_field)
                else:
                    metadata[optional_field] = None

            doc = Document(page_content=str(row.get("review", "")), metadata=metadata)
            documents.append(doc)

        chunked_documents = self.chunk_documents(documents)
        print(f"Transformed {len(chunked_documents)} chunked documents.")
        return chunked_documents

    def store_in_vector_db(self, documents: List[Document]):
        """Store documents into Chroma vector store using upserts and incremental state."""
        persist_directory = os.path.join(os.getcwd(), "chroma_db")
        processed_ids = self._load_processed_ids()
        new_documents: List[Document] = []
        new_ids: List[str] = []

        for document in documents:
            doc_id = self.build_document_id(document)
            if doc_id in processed_ids:
                continue
            new_documents.append(document)
            new_ids.append(doc_id)

        if not new_documents:
            print("No new documents to ingest; existing state already covers the current corpus.")
            return None, []

        vstore = create_chroma_store(
            collection_name=self.config["chroma"]["collection_name"],
            embedding_function=self.model_loader.load_embeddings(),
            chroma_api_key=self.chroma_api_key,
            chroma_tenant=self.chroma_tenant,
            chroma_database=self.chroma_database,
            persist_directory=persist_directory,
            storage_mode=os.getenv("CHROMA_STORAGE_MODE", "auto"),
        )
        try:
            inserted_ids = vstore.add_documents(new_documents, ids=new_ids)
        except Exception as exc:
            if "quota" not in str(exc).lower() and "rate limit" not in str(exc).lower():
                raise
            print("Cloud Chroma quota exceeded; retrying with local persistence.")
            vstore = create_chroma_store(
                collection_name=self.config["chroma"]["collection_name"],
                embedding_function=self.model_loader.load_embeddings(),
                chroma_api_key=None,
                chroma_tenant=None,
                chroma_database=None,
                persist_directory=persist_directory,
                storage_mode="local",
            )
            inserted_ids = vstore.add_documents(new_documents, ids=new_ids)

        self._save_processed_ids(new_ids)
        self._write_keyword_index(new_documents)
        print(f"Successfully inserted {len(inserted_ids)} new chunked documents into Chroma.")
        return vstore, inserted_ids

    def run_pipeline(self):
        """Run the full data ingestion pipeline: transform data and store into the vector DB."""
        documents = self.transform_data()
        vstore, inserted_ids = self.store_in_vector_db(documents)
        if not vstore:
            return

        query = "Can you tell me the low budget headphone?"
        results = vstore.similarity_search(query)

        print(f"\nSample search results for query: '{query}'")
        for res in results:
            print(f"Content: {res.page_content}\nMetadata: {res.metadata}\n")


if __name__ == "__main__":
    ingestion = DataIngestion()
    ingestion.run_pipeline()
