import json
import logging
import os
import re
from typing import List

from dotenv import load_dotenv
from langchain_core.documents import Document

from utils.chroma_utils import create_chroma_store
from utils.config_loader import load_config
from utils.model_loader import ModelLoader

logger = logging.getLogger(__name__)


class Retriever:

    def __init__(self):
        self.model_loader = ModelLoader()
        self.config = load_config()
        self._load_env_variables()
        self.vstore = None
        self.retriever = None
        self.keyword_index_path = os.path.join(os.getcwd(), self.config.get("ingestion", {}).get("keyword_index_file", "data/.keyword_index.json"))

    def _load_env_variables(self):
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

    def load_retriever(self):
        try:
            if not self.vstore:
                self.vstore = create_chroma_store(
                    collection_name=self.config["chroma"]["collection_name"],
                    embedding_function=self.model_loader.load_embeddings(),
                    chroma_api_key=self.chroma_api_key,
                    chroma_tenant=self.chroma_tenant,
                    chroma_database=self.chroma_database,
                    persist_directory=os.path.join(os.getcwd(), "chroma_db"),
                    storage_mode=os.getenv("CHROMA_STORAGE_MODE", "auto"),
                )
            if not self.retriever:
                top_k = self.config["retriever"]["top_k"] if "retriever" in self.config else 3
                self.retriever = self.vstore.as_retriever(search_kwargs={"k": top_k})
                logger.info("Retriever loaded successfully with top_k=%s.", top_k)
            return self.retriever
        except Exception as exc:
            raise RuntimeError("Failed to load Chroma retriever.") from exc

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def keyword_search(self, query: str, top_k: int = 5) -> List[Document]:
        if not os.path.exists(self.keyword_index_path):
            return []

        with open(self.keyword_index_path, "r", encoding="utf-8") as handle:
            keyword_index = json.load(handle)

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scored_results = []
        for doc_id, payload in keyword_index.items():
            tokens = payload.get("tokens", {})
            score = sum(tokens.get(token, 0) for token in query_tokens)
            if score > 0:
                scored_results.append((score, doc_id, payload))

        scored_results.sort(reverse=True)
        results = []
        for _, _, payload in scored_results[:top_k]:
            results.append(Document(page_content=payload.get("text", ""), metadata=payload.get("metadata", {})))
        return results

    def call_retriever(self, query: str) -> List[Document]:
        try:
            retriever = self.load_retriever()
            vector_output = retriever.invoke(query)
            keyword_output = self.keyword_search(query, top_k=max(3, len(vector_output)))

            merged_output: List[Document] = []
            seen_pairs = set()
            for document in vector_output + keyword_output:
                match_key = (
                    document.metadata.get("source_id"),
                    document.page_content,
                )
                if match_key in seen_pairs:
                    continue
                seen_pairs.add(match_key)
                merged_output.append(document)

            return merged_output[: self.config["retriever"]["top_k"] if "retriever" in self.config else 3]
        except Exception as exc:
            raise RuntimeError("Failed to retrieve relevant documents.") from exc


if __name__ == "__main__":
    retriever_obj = Retriever()
    user_query = "Can you suggest good budget laptops?"
    results = retriever_obj.call_retriever(user_query)

    for idx, doc in enumerate(results, 1):
        print(f"Result {idx}: {doc.page_content}\nMetadata: {doc.metadata}\n")
