import os
from typing import Optional

from langchain_chroma import Chroma


def create_chroma_store(
    collection_name: str,
    embedding_function,
    chroma_api_key: Optional[str] = None,
    chroma_tenant: Optional[str] = None,
    chroma_database: Optional[str] = None,
    persist_directory: Optional[str] = None,
    create_collection_if_not_exists: bool = True,
    storage_mode: Optional[str] = None,
):
    """Create a Chroma vector store using cloud config when requested, otherwise local persistence."""
    if persist_directory is None:
        persist_directory = os.path.join(os.getcwd(), "chroma_db")

    os.makedirs(persist_directory, exist_ok=True)

    storage_mode = (storage_mode or os.getenv("CHROMA_STORAGE_MODE", "auto")).strip().lower()
    cloud_ready = all([chroma_api_key, chroma_tenant, chroma_database])

    if storage_mode in {"cloud", "remote"}:
        if not cloud_ready:
            raise RuntimeError("Cloud Chroma storage requested, but CHROMA_API_KEY, CHROMA_TENANT, and CHROMA_DATABASE are not configured.")
        return Chroma(
            collection_name=collection_name,
            embedding_function=embedding_function,
            chroma_cloud_api_key=chroma_api_key,
            tenant=chroma_tenant,
            database=chroma_database,
            create_collection_if_not_exists=create_collection_if_not_exists,
        )

    if storage_mode in {"local", "persist", "filesystem"}:
        return Chroma(
            collection_name=collection_name,
            embedding_function=embedding_function,
            persist_directory=persist_directory,
            create_collection_if_not_exists=create_collection_if_not_exists,
        )

    if cloud_ready:
        try:
            return Chroma(
                collection_name=collection_name,
                embedding_function=embedding_function,
                chroma_cloud_api_key=chroma_api_key,
                tenant=chroma_tenant,
                database=chroma_database,
                create_collection_if_not_exists=create_collection_if_not_exists,
            )
        except Exception as exc:
            if _should_fallback_to_local(exc):
                print("Cloud Chroma connection failed; falling back to local persistence.")
            else:
                raise

    return Chroma(
        collection_name=collection_name,
        embedding_function=embedding_function,
        persist_directory=persist_directory,
        create_collection_if_not_exists=create_collection_if_not_exists,
    )


def _should_fallback_to_local(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ["quota", "rate limit", "forbidden", "unauthorized", "timeout", "connection", "not found", "not available", "403", "401", "404", "500"])
