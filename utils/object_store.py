"""Cloud-agnostic object storage helpers.

The ingestion pipeline reads PDFs from a "landing" location and writes its
state / BM25 index back out. In local development that location is a plain
folder on disk. In production it is a GCS, S3, or ADLS bucket. This module
is the only place that knows how to open either kind of location, via
fsspec, so the rest of the ingestion code just deals in URIs like:

    data/landing              (local dev, relative path)
    gs://my-bucket/landing    (GCS)
    s3://my-bucket/landing    (S3)
    abfs://container/landing  (Azure Data Lake)

Swapping environments is a one-line config change (`ingestion.landing_path`
in config/config.yaml or the LANDING_PATH env var) -- no code change.

Cloud backends need their optional fsspec implementation installed:
    pip install gcsfs   # for gs://
    pip install s3fs    # for s3://
    pip install adlfs   # for abfs://
These are NOT required for local development.
"""
import json
import logging
from typing import Any, Iterable, List, Optional

import fsspec

logger = logging.getLogger(__name__)


def get_fs(uri: str):
    """Return (filesystem, normalized_path) for a URI, local or cloud."""
    fs, path = fsspec.core.url_to_fs(uri)
    return fs, path


def ensure_dir(uri: str) -> None:
    fs, path = get_fs(uri)
    try:
        fs.makedirs(path, exist_ok=True)
    except NotImplementedError:
        # Some object stores (plain S3/GCS) don't have real directories --
        # that's fine, writes will create the prefix implicitly.
        pass


def list_files(uri: str, suffixes: Optional[Iterable[str]] = None) -> List[str]:
    """List files under a URI (non-recursive by default). Returns full URIs."""
    fs, path = get_fs(uri)
    if not fs.exists(path):
        return []
    scheme = fsspec.core.split_protocol(uri)[0]
    prefix = f"{scheme}://" if scheme else ""
    entries = fs.find(path)
    if suffixes:
        suffix_tuple = tuple(s.lower() for s in suffixes)
        entries = [entry for entry in entries if entry.lower().endswith(suffix_tuple)]
    return sorted(f"{prefix}{entry}" for entry in entries)


def read_bytes(uri: str) -> bytes:
    fs, path = get_fs(uri)
    with fs.open(path, "rb") as handle:
        return handle.read()


def read_json(uri: str, default: Any = None) -> Any:
    fs, path = get_fs(uri)
    if not fs.exists(path):
        return default
    with fs.open(path, "r") as handle:
        return json.load(handle)


def write_json(uri: str, payload: Any) -> None:
    fs, path = get_fs(uri)
    parent = path.rsplit("/", 1)[0] if "/" in path else ""
    if parent:
        try:
            fs.makedirs(parent, exist_ok=True)
        except NotImplementedError:
            pass
    with fs.open(path, "w") as handle:
        json.dump(payload, handle, indent=2)


def file_fingerprint(uri: str) -> str:
    """A cheap, storage-agnostic change signal for a file: size + mtime if
    available, falling back to just the path. Good enough to decide whether
    a landing file needs (re)processing without downloading it first."""
    fs, path = get_fs(uri)
    try:
        info = fs.info(path)
        size = info.get("size")
        mtime = info.get("mtime") or info.get("LastModified")
        return f"{path}:{size}:{mtime}"
    except Exception:
        logger.warning("Could not stat %s for fingerprinting; using path only.", uri)
        return path
