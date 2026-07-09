import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Tuple

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

    def parse_metadata_filters(self, query: str) -> Dict[str, Dict[str, Any]]:
        filters: Dict[str, Dict[str, Any]] = {}
        if not query:
            return filters

        for match in re.finditer(r"\b(rating|price|category|product_name|brand)\s*(>=|<=|>|<|=|:)\s*([0-9.]+|[a-zA-Z0-9-]+)", query, flags=re.IGNORECASE):
            field = match.group(1).lower()
            operator = match.group(2)
            value = match.group(3)

            normalized_field = "product_rating" if field == "rating" else field
            normalized_value: Any = value
            if operator in {">=", "<=", ">", "<"}:
                try:
                    normalized_value = float(value)
                except ValueError:
                    normalized_value = value
            elif operator in {":", "="}:
                normalized_value = value.lower()

            if normalized_field == "product_rating" and isinstance(normalized_value, (int, float)):
                filters[normalized_field] = {operator: normalized_value}
            else:
                filters[normalized_field] = {"contains": normalized_value}

        return filters

    def rewrite_query(self, query: str) -> str:
        rewritten = query.strip()
        replacements = {
            "headphone": "headphones earphones earbuds",
            "headphones": "headphones earphones earbuds",
            "earphone": "earphones earbuds",
            "buds": "earbuds",
            "budget": "budget affordable cheap low cost",
            "cheap": "budget affordable cheap low cost",
            "good": "good quality reliable",
        }
        for term, expansion in replacements.items():
            pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            rewritten = pattern.sub(expansion, rewritten)
        return rewritten

    def apply_metadata_filters(self, documents: List[Document], filters: Dict[str, Dict[str, Any]]) -> List[Document]:
        if not filters:
            return documents

        filtered_documents: List[Document] = []
        for doc in documents:
            metadata = doc.metadata or {}
            keep = True
            for field, clauses in filters.items():
                normalized_field = "product_rating" if field == "rating" else field
                metadata_value = metadata.get(normalized_field)
                if metadata_value is None:
                    keep = False
                    break
                for operator, value in clauses.items():
                    if operator == ">=" and not (metadata_value >= value):
                        keep = False
                        break
                    if operator == "<=" and not (metadata_value <= value):
                        keep = False
                        break
                    if operator == ">" and not (metadata_value > value):
                        keep = False
                        break
                    if operator == "<" and not (metadata_value < value):
                        keep = False
                        break
                    if operator == "contains" and str(metadata_value).lower().find(str(value).lower()) == -1:
                        keep = False
                        break
            if keep:
                filtered_documents.append(doc)
        return filtered_documents

    def rrf_merge(self, dense_results: List[Document], sparse_results: List[Document], k: int = 60) -> List[Document]:
        scores: Dict[Tuple[Any, str], float] = {}
        ranked_sources = [dense_results, sparse_results]

        for source_results in ranked_sources:
            for rank, doc in enumerate(source_results):
                doc_id = (doc.metadata.get("source_id"), doc.page_content)
                scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1))

        sorted_docs = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        output: List[Document] = []
        for (source_id, page_content), _ in sorted_docs:
            matched_doc = None
            for candidate in dense_results + sparse_results:
                if candidate.metadata.get("source_id") == source_id and candidate.page_content == page_content:
                    matched_doc = candidate
                    break
            if matched_doc is not None:
                output.append(matched_doc)
        return output

    def rerank_documents(self, documents: List[Document], query: str, filters: Dict[str, Dict[str, Any]]) -> List[Document]:
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return documents

        ranked_documents: List[Tuple[float, Document]] = []
        for doc in documents:
            content_tokens = set(self._tokenize(doc.page_content or ""))
            overlap = len(query_tokens.intersection(content_tokens)) / max(1, len(query_tokens))
            metadata_bonus = 0.0
            if filters.get("product_rating") and doc.metadata.get("product_rating") is not None:
                metadata_bonus += 0.05
            if any(term in query.lower() for term in ["budget", "cheap", "affordable"]):
                if str(doc.metadata.get("product_name", "")).lower().find("budget") != -1:
                    metadata_bonus += 0.05
            score = overlap + metadata_bonus
            ranked_documents.append((score, doc))

        ranked_documents.sort(key=lambda item: item[0], reverse=True)
        return [document for _, document in ranked_documents]

    def dynamic_top_k(self, documents: List[Document]) -> int:
        if len(documents) <= 3:
            return len(documents)
        if len(documents) <= 6:
            return 4
        return 5

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
            rewritten_query = self.rewrite_query(query)
            filters = self.parse_metadata_filters(query)
            retriever = self.load_retriever()
            vector_output = retriever.invoke(rewritten_query)
            vector_output = self.apply_metadata_filters(vector_output, filters)
            keyword_output = self.keyword_search(rewritten_query, top_k=max(6, len(vector_output) * 2))
            keyword_output = self.apply_metadata_filters(keyword_output, filters)

            merged_output = self.rrf_merge(vector_output, keyword_output)
            reranked_output = self.rerank_documents(merged_output, rewritten_query, filters)
            top_k = self.dynamic_top_k(reranked_output)
            return reranked_output[:top_k]
        except Exception as exc:
            raise RuntimeError("Failed to retrieve relevant documents.") from exc


if __name__ == "__main__":
    retriever_obj = Retriever()
    user_query = "Can you suggest good budget laptops?"
    results = retriever_obj.call_retriever(user_query)

    for idx, doc in enumerate(results, 1):
        print(f"Result {idx}: {doc.page_content}\nMetadata: {doc.metadata}\n")
