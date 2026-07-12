"""BM25 keyword index, persisted alongside the vector store's source data.

Replaces the earlier ad-hoc token-count "keyword search" with a real BM25Okapi
ranking. The index is a plain JSON document (tokenized corpus + doc payloads)
written through utils.object_store, so it lives in the same landing bucket as
everything else and needs no separate infrastructure.
"""
import logging
import re
from typing import Any, Dict, List, Tuple

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from utils.object_store import read_json, write_json

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


class BM25Index:
    """Wraps a BM25Okapi model plus the documents it was built from."""

    def __init__(self, corpus_ids: List[str], texts: List[str], metadatas: List[Dict[str, Any]]):
        self.corpus_ids = corpus_ids
        self.texts = texts
        self.metadatas = metadatas
        tokenized_corpus = [tokenize(text) for text in texts]
        self._bm25 = BM25Okapi(tokenized_corpus) if tokenized_corpus else None

    def search(self, query: str, top_k: int = 5) -> List[Document]:
        if not self._bm25:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        results: List[Document] = []
        for idx in ranked[:top_k]:
            if scores[idx] <= 0:
                break
            results.append(Document(page_content=self.texts[idx], metadata=self.metadatas[idx]))
        return results

    def to_payload(self) -> Dict[str, Any]:
        return {
            "corpus_ids": self.corpus_ids,
            "texts": self.texts,
            "metadatas": self.metadatas,
        }

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "BM25Index":
        return cls(
            corpus_ids=payload.get("corpus_ids", []),
            texts=payload.get("texts", []),
            metadatas=payload.get("metadatas", []),
        )

    @classmethod
    def empty(cls) -> "BM25Index":
        return cls([], [], [])


def load_index(index_uri: str) -> BM25Index:
    payload = read_json(index_uri, default=None)
    if not payload:
        return BM25Index.empty()
    return BM25Index.from_payload(payload)


def upsert_index(index_uri: str, new_ids: List[str], new_docs: List[Document]) -> BM25Index:
    """Merge new chunks into the existing persisted BM25 index (dedup by id)
    and write the result back out. Called by the ingestion pipeline after
    every incremental batch, so the index always reflects the vector store."""
    existing = load_index(index_uri)
    seen: Dict[str, Tuple[str, Dict[str, Any]]] = {
        doc_id: (text, meta)
        for doc_id, text, meta in zip(existing.corpus_ids, existing.texts, existing.metadatas)
    }
    for doc_id, doc in zip(new_ids, new_docs):
        seen[doc_id] = (doc.page_content, doc.metadata)

    corpus_ids = list(seen.keys())
    texts = [seen[doc_id][0] for doc_id in corpus_ids]
    metadatas = [seen[doc_id][1] for doc_id in corpus_ids]
    merged = BM25Index(corpus_ids, texts, metadatas)
    write_json(index_uri, merged.to_payload())
    logger.info("BM25 index updated: %d total chunks (%d new).", len(corpus_ids), len(new_ids))
    return merged
