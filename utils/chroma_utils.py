import os
import logging
from typing import Optional

from langchain_chroma import Chroma

logger = logging.getLogger(__name__)


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

    if storage_mode in {"local", "persist", "filesystem"}:
        logger.info("Chroma storage mode explicitly set to local; using persist_directory=%s.", persist_directory)
        return Chroma(
            collection_name=collection_name,
            embedding_function=embedding_function,
            persist_directory=persist_directory,
            create_collection_if_not_exists=create_collection_if_not_exists,
        )

    # storage_mode is "cloud"/"remote" OR "auto" with cloud credentials present.
    # Either way: once cloud is configured, ALWAYS use it. No silent retry on
    # a local store -- a quota/timeout/auth failure here must surface as a
    # loud error, not quietly fork the data into a second, divergent index
    # that only this one replica/process can see.
    if storage_mode in {"cloud", "remote"} or cloud_ready:
        if not cloud_ready:
            raise RuntimeError(
                "Cloud Chroma storage requested (CHROMA_STORAGE_MODE=cloud), but "
                "CHROMA_API_KEY, CHROMA_TENANT, and CHROMA_DATABASE are not fully configured."
            )
        logger.info("Using Chroma Cloud (tenant=%s, database=%s).", chroma_tenant, chroma_database)
        return Chroma(
            collection_name=collection_name,
            embedding_function=embedding_function,
            chroma_cloud_api_key=chroma_api_key,
            tenant=chroma_tenant,
            database=chroma_database,
            create_collection_if_not_exists=create_collection_if_not_exists,
        )

    # No cloud credentials anywhere and no explicit mode -- genuine local dev.
    # This is the ONLY path that reaches local persistence, and it's logged
    # loudly (not swallowed) so nobody mistakes it for the cloud store.
    logger.warning(
        "No CHROMA_API_KEY/CHROMA_TENANT/CHROMA_DATABASE configured and "
        "CHROMA_STORAGE_MODE is not 'cloud'; using local persistence at %s. "
        "Set these env vars (or pass storage_mode='cloud') to use Chroma Cloud instead.",
        persist_directory,
    )
    return Chroma(
        collection_name=collection_name,
        embedding_function=embedding_function,
        persist_directory=persist_directory,
        create_collection_if_not_exists=create_collection_if_not_exists,
    )
