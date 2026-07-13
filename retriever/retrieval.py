import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from langchain_core.documents import Document

from retriever.query_rewriter import contextualize_query
from utils.bm25_index import load_index
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
        ingestion_cfg = self.config.get("ingestion", {})
        index_path = os.getenv("INDEX_PATH", ingestion_cfg.get("index_path", "data/landing/_index"))
        self.bm25_index_uri = f"{index_path.rstrip('/')}/bm25_index.json"
        self._bm25_index = None
        self._bm25_loaded_at = 0.0
        # Reload the persisted BM25 index at most this often -- it's rebuilt
        # by the ingestion job, not this process, so a short TTL is enough to
        # pick up new content without re-reading it on every single query.
        self._bm25_refresh_seconds = int(os.getenv("BM25_REFRESH_SECONDS", "60"))

        self.cohere_api_key = os.getenv("COHERE_API_KEY")
        self._reranker = None
        self._rewrite_llm = None
        self.last_standalone_query = None

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
                top_k = self._candidate_pool_top_k()
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

            if operator in {">=", "<=", ">", "<"} and isinstance(normalized_value, (int, float)):
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

    def _load_bm25_index(self):
        now = time.time()
        if self._bm25_index is None or (now - self._bm25_loaded_at) > self._bm25_refresh_seconds:
            self._bm25_index = load_index(self.bm25_index_uri)
            self._bm25_loaded_at = now
        return self._bm25_index

    def keyword_search(self, query: str, top_k: int = 5) -> List[Document]:
        bm25_index = self._load_bm25_index()
        return bm25_index.search(query, top_k=top_k)

    def _load_rewrite_llm(self):
        if self._rewrite_llm is None:
            rewrite_model_name = self.config.get("llm", {}).get("rewrite_model_name")
            self._rewrite_llm = self.model_loader.load_llm(model_name=rewrite_model_name)
        return self._rewrite_llm

    def _candidate_pool_top_k(self) -> int:
        """How many dense/BM25 candidates to fetch before merge+rerank.
        Wider only when Cohere Rerank is actually active -- a real semantic
        reranker benefits from more candidates, but the crude lexical
        fallback reranker gets *worse* with a wider pool (more chances for
        an irrelevant-but-lexically-similar document to outrank the
        genuinely relevant one), so it keeps the narrow default."""
        retriever_cfg = self.config.get("retriever", {}) if self.config else {}
        if self.cohere_api_key:
            return int(retriever_cfg.get("rerank_candidate_top_k", 20))
        return int(retriever_cfg.get("top_k", 10))

    def _rerank_with_cohere(self, documents: List[Document], query: str, top_n: int) -> List[Document]:
        from langchain_cohere import CohereRerank

        retriever_cfg = self.config.get("retriever", {})
        if self._reranker is None:
            self._reranker = CohereRerank(
                cohere_api_key=self.cohere_api_key,
                model=retriever_cfg.get("rerank_model", "rerank-english-v3.0"),
                top_n=top_n,
            )
        reranked = list(self._reranker.compress_documents(documents=documents, query=query))
        relevance_floor = retriever_cfg.get("rerank_relevance_floor")
        if relevance_floor is not None:
            reranked = [doc for doc in reranked if doc.metadata.get("relevance_score", 1.0) >= relevance_floor]
        return reranked

    def _rerank(self, documents: List[Document], query: str, filters: Dict[str, Dict[str, Any]]) -> List[Document]:
        if not documents:
            return []

        top_n = int(self.config.get("retriever", {}).get("rerank_top_k", 5))

        if self.cohere_api_key:
            try:
                return self._rerank_with_cohere(documents, query, top_n)
            except Exception:
                logger.exception("Cohere rerank failed; falling back to lexical term-overlap reranking.")
        else:
            logger.warning(
                "COHERE_API_KEY not configured; using lexical term-overlap reranking instead of "
                "semantic reranking. Set COHERE_API_KEY for production-quality reranking."
            )

        reranked_documents = self.rerank_documents(documents, query, filters)
        fallback_top_k = self.dynamic_top_k(reranked_documents)
        return reranked_documents[:fallback_top_k]

    def call_retriever(self, query: str, chat_history: str = None) -> List[Document]:
        try:
            resolved_query = query
            if chat_history:
                resolved_query = contextualize_query(query, chat_history, self._load_rewrite_llm)
            self.last_standalone_query = resolved_query

            rewritten_query = self.rewrite_query(resolved_query)
            filters = self.parse_metadata_filters(query)
            retriever = self.load_retriever()

            keyword_top_k = max(6, self._candidate_pool_top_k() * 2)

            # Dense and sparse lookups are independent I/O calls -- run them
            # concurrently instead of sequentially to offset the added
            # latency from query contextualization and semantic reranking.
            with ThreadPoolExecutor(max_workers=2) as executor:
                vector_future = executor.submit(retriever.invoke, rewritten_query)
                keyword_future = executor.submit(self.keyword_search, rewritten_query, keyword_top_k)
                vector_output = self.apply_metadata_filters(vector_future.result(), filters)
                keyword_output = self.apply_metadata_filters(keyword_future.result(), filters)

            merged_output = self.rrf_merge(vector_output, keyword_output)
            return self._rerank(merged_output, rewritten_query, filters)
        except Exception as exc:
            raise RuntimeError("Failed to retrieve relevant documents.") from exc


if __name__ == "__main__":
    retriever_obj = Retriever()
    user_query = "Can you suggest good budget laptops?"
    results = retriever_obj.call_retriever(user_query)

    for idx, doc in enumerate(results, 1):
        print(f"Result {idx}: {doc.page_content}\nMetadata: {doc.metadata}\n")
