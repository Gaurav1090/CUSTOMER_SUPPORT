import hashlib
import io
import json
import logging
import os
import re
from typing import Any, Dict, List

import pandas as pd
from dotenv import load_dotenv
from langchain_core.documents import Document
from pypdf import PdfReader

from utils.bm25_index import upsert_index
from utils.chroma_utils import create_chroma_store
from utils.config_loader import load_config
from utils.model_loader import ModelLoader
from utils.object_store import ensure_dir, file_fingerprint, list_files, move_file, read_bytes, read_json, write_json
from utils.pii import redact_pii

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_text(text: str) -> str:
    """Normalize extracted PDF text: strip control chars, collapse repeated
    whitespace/blank lines. Deliberately simple -- swap in a heavier cleaner
    (e.g. unstructured's cleaners) later if OCR noise becomes an issue."""
    if not text:
        return ""
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _clean_field(value: Any) -> str:
    """Stringify a CSV cell for embedding, dropping missing/NaN values
    instead of literally embedding the text "nan"."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


class DataIngestion:
    """Incremental ingestion job: landing storage (GCS/S3/ADLS/local) -> clean
    -> dedupe -> chunk -> upsert to the vector store -> update BM25 index.

    Designed to run as a stateless, repeatable job (e.g. a Cloud Run Job on a
    schedule or a GCS event trigger): all state (processed-file manifest,
    processed-chunk ids, BM25 index) is read from and written back to the
    same object storage as the source documents, not local disk. Running it
    twice on the same files is a no-op.
    """

    def __init__(self):
        self.config = load_config()
        self.model_loader = ModelLoader()
        self._load_env_variables()

        ingestion_cfg = self.config.get("ingestion", {})
        self.landing_path = os.getenv("LANDING_PATH", ingestion_cfg.get("landing_path", "data/landing"))
        self.index_path = os.getenv("INDEX_PATH", ingestion_cfg.get("index_path", "data/landing/_index"))
        self.archive_path = os.getenv("ARCHIVE_PATH", ingestion_cfg.get("archive_path", "data/landing/_archive"))
        self.supported_extensions = tuple(ingestion_cfg.get("supported_extensions", [".pdf"]))
        self.chunk_size = int(ingestion_cfg.get("chunk_size", 400))
        self.chunk_overlap = int(ingestion_cfg.get("chunk_overlap", 80))

        self.state_uri = f"{self.index_path.rstrip('/')}/ingestion_state.json"
        self.bm25_index_uri = f"{self.index_path.rstrip('/')}/bm25_index.json"

        ensure_dir(self.landing_path)
        ensure_dir(self.archive_path)
        logger.info("Ingestion landing path: %s", self.landing_path)

    def _load_env_variables(self):
        load_dotenv()
        required_vars = []
        if self.config["embedding_model"]["provider"] == "google":
            required_vars.append("GOOGLE_API_KEY")
        missing_vars = [var for var in required_vars if os.getenv(var) is None]
        if missing_vars:
            raise EnvironmentError(f"Missing environment variables: {missing_vars}")

        self.chroma_api_key = os.getenv("CHROMA_API_KEY")
        self.chroma_tenant = os.getenv("CHROMA_TENANT")
        self.chroma_database = os.getenv("CHROMA_DATABASE")

    # ---------------------------------------------------------------- state

    def _load_state(self) -> Dict[str, Any]:
        return read_json(self.state_uri, default={"processed_files": {}, "processed_chunk_ids": []})

    def _save_state(self, state: Dict[str, Any]) -> None:
        write_json(self.state_uri, state)

    # ------------------------------------------------------------- loading

    def _discover_new_files(self, state: Dict[str, Any]) -> List[str]:
        """List files under the landing path whose fingerprint (size/mtime)
        has changed since the last run -- this is the incremental step at
        the file level, before we even open anything."""
        all_files = list_files(self.landing_path, suffixes=self.supported_extensions)
        processed = state.get("processed_files", {})
        new_or_changed = [uri for uri in all_files if processed.get(uri) != file_fingerprint(uri)]
        logger.info("Landing path has %d files, %d new/changed.", len(all_files), len(new_or_changed))
        return new_or_changed

    def _dispatch_loader(self, uri: str) -> List[Document]:
        """Route a landing file to the right loader by extension. Add a new
        branch here (plus the matching suffix in config.yaml's
        supported_extensions) whenever a new format needs support."""
        lower_uri = uri.lower()
        if lower_uri.endswith(".pdf"):
            return self._load_pdf_documents(uri)
        if lower_uri.endswith(".csv"):
            return self._load_csv_documents(uri)
        logger.warning("No loader registered for %s; skipping.", uri)
        return []

    def _load_pdf_documents(self, uri: str) -> List[Document]:
        """Extract per-page text from a PDF in the landing storage. Returns
        one Document per non-empty page; downstream chunking splits further."""
        raw_bytes = read_bytes(uri)
        documents: List[Document] = []
        try:
            reader = PdfReader(io.BytesIO(raw_bytes))
        except Exception:
            logger.exception("Failed to open PDF %s; skipping.", uri)
            return []

        source_file = uri.rsplit("/", 1)[-1]
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = clean_text(page.extract_text() or "")
                text = redact_pii(text)
            except Exception:
                logger.exception("Failed to extract text from %s page %d; skipping page.", uri, page_number)
                continue
            if not text:
                continue
            documents.append(
                Document(
                    page_content=text,
                    metadata={
                        "source_file": source_file,
                        "source_uri": uri,
                        "page_number": page_number,
                        # TODO(multimodal): when we start extracting images/tables
                        # from pages, tag those chunks with modality="image" /
                        # "table" and route them to a separate embedding model
                        # instead of overloading this text-only field.
                        "modality": "text",
                    },
                )
            )
        return documents

    _REVIEW_COLUMNS = {"product_title", "rating", "summary", "review"}

    def _documents_from_dataframe(self, df: "pd.DataFrame", source_file: str, source_uri: str) -> List[Document]:
        """Turn a CSV's rows into Documents. Recognizes the review-style
        schema (product_title/rating/summary/review) used by the bundled
        demo dataset and gives it structured metadata for the rating/price
        filters in retriever/retrieval.py. Any other CSV shape falls back to
        a generic "flatten every column into text" row, so an arbitrary CSV
        dropped in the landing folder still ingests instead of erroring out."""
        documents: List[Document] = []
        is_review_style = self._REVIEW_COLUMNS.issubset(set(df.columns))

        for index, row in df.iterrows():
            source_id = f"{source_file}:row-{index + 1}"
            if is_review_style:
                metadata: Dict[str, Any] = {
                    "product_name": row.get("product_title"),
                    "product_rating": row.get("rating"),
                    "product_summary": row.get("summary"),
                    "source_row": int(index + 1),
                    "source_file": source_file,
                    "source_uri": source_uri,
                    "source_id": source_id,
                    "modality": "text",
                }
                for optional_field in ("price", "category", "brand"):
                    metadata[optional_field] = row.get(optional_field) if optional_field in row.index else None

                # Embed product context alongside the review text itself --
                # previously only the review was embedded, so a query naming
                # the product ("How is Boat Rockerzz") only matched if a
                # review happened to repeat those words. product_title/
                # rating/summary were metadata-only, invisible to both dense
                # and BM25 search (which both index off page_content).
                #
                # Only the Review field is redacted below (not Product/
                # Rating/Summary): those three are structured catalog data
                # that can't contain a customer's PII, and running the
                # NER pass over them risks false positives on brand/product
                # names (e.g. "BoAt" misread as a LOCATION entity) that
                # would permanently corrupt the product identity in the
                # vector store. Review is freeform customer text, the only
                # field where real PII could actually show up.
                labeled_fields = (
                    ("Product", _clean_field(row.get("product_title"))),
                    ("Rating", _clean_field(row.get("rating"))),
                    ("Summary", _clean_field(row.get("summary"))),
                    ("Review", redact_pii(_clean_field(row.get("review")))),
                )
                page_content = clean_text(
                    "\n".join(f"{label}: {value}" for label, value in labeled_fields if value)
                )
            else:
                metadata = {
                    "source_row": int(index + 1),
                    "source_file": source_file,
                    "source_uri": source_uri,
                    "source_id": source_id,
                    "modality": "text",
                }
                page_content = clean_text(", ".join(f"{col}: {row[col]}" for col in df.columns))
                # Unknown schema -- can't tell which columns are freeform
                # customer text vs. structured data, so redact the whole
                # row as the safer default (unlike the review-style branch
                # above, which redacts only the known-freeform Review field).
                page_content = redact_pii(page_content)

            if page_content:
                documents.append(Document(page_content=page_content, metadata=metadata))
        return documents

    def _load_csv_documents(self, uri: str) -> List[Document]:
        """Any CSV dropped in the landing folder -- not just the bundled
        demo file. Same object-store read path as PDFs, so this works
        identically whether landing_path is local or gs://\\s3://\\abfs://."""
        try:
            raw_bytes = read_bytes(uri)
            df = pd.read_csv(io.BytesIO(raw_bytes))
        except Exception:
            logger.exception("Failed to read CSV %s; skipping.", uri)
            return []
        source_file = uri.rsplit("/", 1)[-1]
        return self._documents_from_dataframe(df, source_file, uri)

    def _load_legacy_csv_documents(self) -> List[Document]:
        """The original Flipkart review CSV at a fixed path, kept only for
        the bundled demo / tests -- gated by INGEST_LEGACY_CSV, separate
        from the landing folder scan. Prefer dropping CSVs into
        landing_path instead; that path is picked up automatically and
        tracked incrementally like everything else."""
        csv_path = self.config.get("ingestion", {}).get("legacy_csv_path", "data/flipkart_product_review.csv")
        if not os.path.exists(csv_path):
            return []
        df = pd.read_csv(csv_path)
        expected_columns = {"product_title", "rating", "summary", "review"}
        if not expected_columns.issubset(set(df.columns)):
            raise ValueError(f"CSV must contain columns: {expected_columns}")
        return self._documents_from_dataframe(df, os.path.basename(csv_path), csv_path)

    # ------------------------------------------------------------ chunking

    def _create_splitter(self):
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError:
            return None
        return RecursiveCharacterTextSplitter(chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap)

    def chunk_documents(self, documents: List[Document]) -> List[Document]:
        splitter = self._create_splitter()
        chunked_documents: List[Document] = []

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
                        end = min(len(text), start + self.chunk_size)
                        chunk_text = text[start:end].strip()
                        if not chunk_text:
                            break
                        split_docs.append(Document(page_content=chunk_text, metadata=dict(parent_metadata)))
                        if end >= len(text):
                            break
                        start = max(0, end - self.chunk_overlap)

            if not split_docs:
                continue
            for index, chunk in enumerate(split_docs):
                metadata = dict(parent_metadata)
                metadata.update(
                    {
                        "chunk_index": index,
                        "chunk_count": len(split_docs),
                        "source_id": parent_metadata.get("source_id")
                        or f"{parent_metadata.get('source_file', 'document')}:p{parent_metadata.get('page_number', 0)}",
                    }
                )
                chunk.metadata = metadata
                chunked_documents.append(chunk)

        return chunked_documents

    # -------------------------------------------------------------- dedupe

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

    # ------------------------------------------------------------- upsert

    def store_in_vector_db(self, documents: List[Document], state: Dict[str, Any]):
        """Upsert only genuinely new chunks (content-hash dedupe) into the
        vector store, then update the BM25 index to match. Cloud Chroma is
        required here and enforced by create_chroma_store -- see
        utils/chroma_utils.py for why there is no local fallback anymore."""
        processed_ids = set(state.get("processed_chunk_ids", []))
        new_documents: List[Document] = []
        new_ids: List[str] = []

        for document in documents:
            doc_id = self.build_document_id(document)
            if doc_id in processed_ids:
                continue
            new_documents.append(document)
            new_ids.append(doc_id)

        if not new_documents:
            logger.info("No new chunks to ingest.")
            return []

        vstore = create_chroma_store(
            collection_name=self.config["chroma"]["collection_name"],
            embedding_function=self.model_loader.load_embeddings(),
            chroma_api_key=self.chroma_api_key,
            chroma_tenant=self.chroma_tenant,
            chroma_database=self.chroma_database,
            storage_mode=os.getenv("CHROMA_STORAGE_MODE", "auto"),
        )

        # Chroma Cloud caps a single write at 300 records (see
        # https://docs.trychroma.com/cloud/quotas-limits). Default to a
        # margin below that in case a future record is larger than usual;
        # override with CHROMA_UPSERT_BATCH_SIZE if you're on a plan with a
        # different limit.
        batch_size = int(os.getenv("CHROMA_UPSERT_BATCH_SIZE", "250"))
        inserted_ids: List[str] = []
        total = len(new_documents)
        for start in range(0, total, batch_size):
            batch_docs = new_documents[start : start + batch_size]
            batch_ids = new_ids[start : start + batch_size]

            batch_inserted = vstore.add_documents(batch_docs, ids=batch_ids)
            inserted_ids.extend(batch_inserted)

            # Persist progress after every batch, not just at the end -- if
            # a later batch hits a transient error (quota, timeout), the
            # chunks already committed here are recorded as processed, so a
            # re-run only retries what's actually left instead of redoing
            # (and double-billing) the whole file.
            upsert_index(self.bm25_index_uri, batch_ids, batch_docs)
            processed_ids.update(batch_ids)
            state["processed_chunk_ids"] = sorted(processed_ids)
            self._save_state(state)
            logger.info("Upserted batch: %d/%d chunks committed so far.", start + len(batch_ids), total)

        logger.info("Inserted %d new chunks into the vector store and BM25 index.", len(inserted_ids))
        return inserted_ids

    # ------------------------------------------------------------- archive

    def _archive_files(self, uris: List[str]) -> None:
        """Move successfully-ingested landing files to the archive prefix
        so landing/ only ever holds files not yet processed -- the
        standard landing -> processed -> archive pattern, instead of
        ingested files sitting in landing/ indefinitely. Best-effort: the
        vector store is already the source of truth for what's ingested by
        this point (state was saved before this runs), so a failed move
        just leaves that file behind in landing/ -- harmless, since its
        fingerprint is already recorded as processed and it won't be
        re-ingested next run either way."""
        for uri in uris:
            filename = uri.rsplit("/", 1)[-1]
            dest_uri = f"{self.archive_path.rstrip('/')}/{filename}"
            try:
                move_file(uri, dest_uri)
                logger.info("Archived %s -> %s", uri, dest_uri)
            except Exception:
                logger.exception("Failed to archive %s; leaving it in landing.", uri)

    # ------------------------------------------------------------- driver

    def run_pipeline(self, include_legacy_csv: bool = False):
        state = self._load_state()

        new_files = self._discover_new_files(state)
        documents: List[Document] = []
        for uri in new_files:
            documents.extend(self._dispatch_loader(uri))

        if include_legacy_csv:
            documents.extend(self._load_legacy_csv_documents())

        if not documents and not new_files:
            logger.info("Nothing new to ingest.")
            return

        chunked_documents = self.chunk_documents(documents)
        logger.info("Chunked into %d passages.", len(chunked_documents))
        self.store_in_vector_db(chunked_documents, state)

        for uri in new_files:
            state.setdefault("processed_files", {})[uri] = file_fingerprint(uri)
        self._save_state(state)

        self._archive_files(new_files)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingestion = DataIngestion()
    ingestion.run_pipeline(include_legacy_csv=os.getenv("INGEST_LEGACY_CSV", "false").lower() == "true")
