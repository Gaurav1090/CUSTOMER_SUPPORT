"""Product-tier RAG metrics: auto-resolution rate, exclusion rate, active
users, and a CSAT proxy -- computed from live Langfuse trace/score data
that's already flowing in from utils/ops.py's tracing (Tier 1 cost
tracking) and utils/ops.py's record_feedback_score (Tier 2 outcome
signal). No new instrumentation -- this only aggregates what's already
being recorded on every real request.

Technical-tier metrics (MRR, precision/recall, faithfulness, groundedness,
P95 latency) already exist in evaluation/evaluator.py's offline golden-set
evaluation. This is the live-traffic counterpart: run periodically (cron,
a scheduled Cloud Run job, or by hand) against a time window, rather than
a fixed test set.

Business-tier metrics (saved revenue, time saved per ticket) are
deliberately NOT computed here -- they need an external business input
this system has no source of (e.g. average human-agent handling cost per
ticket), not something derivable from trace data alone.
"""
import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

TRACE_NAME = "rag-chat"
PAGE_SIZE = 100


def _langfuse_auth() -> HTTPBasicAuth:
    load_dotenv()
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        raise EnvironmentError("LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY must be set to compute product metrics.")
    return HTTPBasicAuth(public_key, secret_key)


def _base_url() -> str:
    return os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com").rstrip("/")


def _paginate(path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Page through a Langfuse public API list endpoint -- caps a single
    page at 100 items, so this follows meta.totalPages rather than
    assuming one page covers the window."""
    auth = _langfuse_auth()
    base_url = _base_url()
    params = dict(params, page=1)

    items: List[Dict[str, Any]] = []
    while True:
        response = requests.get(f"{base_url}{path}", auth=auth, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        items.extend(payload.get("data", []))
        meta = payload.get("meta", {})
        if params["page"] >= meta.get("totalPages", 1):
            break
        params["page"] += 1
    return items


def fetch_traces(since: datetime, until: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """All rag-chat traces in [since, until). Note: unlike the single-trace
    detail endpoint, this list endpoint's "scores" field is a list of score
    ID strings, not full score objects -- use fetch_feedback_scores for
    feedback data instead of reading trace["scores"] here."""
    params: Dict[str, Any] = {"name": TRACE_NAME, "fromTimestamp": since.isoformat(), "limit": PAGE_SIZE}
    if until is not None:
        params["toTimestamp"] = until.isoformat()
    return _paginate("/api/public/traces", params)


def fetch_feedback_scores(since: datetime, until: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """All user_feedback scores in [since, until), via the dedicated scores
    endpoint -- the traces list endpoint doesn't expose full score objects
    (see fetch_traces)."""
    params: Dict[str, Any] = {"name": "user_feedback", "fromTimestamp": since.isoformat(), "limit": PAGE_SIZE}
    if until is not None:
        params["toTimestamp"] = until.isoformat()
    return _paginate("/api/public/scores", params)


def _resolution_status(trace: Dict[str, Any]) -> str:
    """Classify one trace as "resolved", "excluded", or "errored" by
    reading back the same citation_check/groundedness_verdict decision
    main.py's invoke_chain_details already made and recorded as trace
    metadata -- this replays that decision rather than re-deriving
    resolution from raw answer text, so it can never drift from what the
    app actually decided."""
    metadata = trace.get("metadata") or {}
    citation_check = metadata.get("citation_check")
    groundedness_verdict = metadata.get("groundedness_verdict")

    if trace.get("output") is None and citation_check is None:
        return "errored"
    if citation_check == "skipped_no_context":
        return "excluded"
    if citation_check == "failed":
        return "excluded"
    if groundedness_verdict == "failed":
        return "excluded"
    return "resolved"


def _extract_session_id(trace: Dict[str, Any]) -> Optional[str]:
    metadata = trace.get("metadata") or {}
    if metadata.get("session_id"):
        return metadata["session_id"]
    return (trace.get("input") or {}).get("session_id")


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def compute_product_metrics(since: datetime, until: Optional[datetime] = None) -> Dict[str, Any]:
    traces = fetch_traces(since, until)

    total = len(traces)
    statuses = [_resolution_status(trace) for trace in traces]
    resolved = statuses.count("resolved")
    excluded = statuses.count("excluded")
    errored = statuses.count("errored")

    session_ids = {_extract_session_id(trace) for trace in traces}
    session_ids.discard(None)

    feedback_scores = fetch_feedback_scores(since, until)
    feedback_up = sum(1 for score in feedback_scores if score.get("value") == 1)
    feedback_down = sum(1 for score in feedback_scores if score.get("value") == 0)

    return {
        "window_start": since.isoformat(),
        "window_end": (until or datetime.now(timezone.utc)).isoformat(),
        "total_requests": total,
        "active_users": len(session_ids),
        "resolved_requests": resolved,
        "excluded_requests": excluded,
        "errored_requests": errored,
        "auto_resolution_rate": resolved / total if total else None,
        "exclusion_rate": excluded / total if total else None,
        "error_rate": errored / total if total else None,
        "feedback_up": feedback_up,
        "feedback_down": feedback_down,
        "csat_proxy": feedback_up / (feedback_up + feedback_down) if (feedback_up + feedback_down) else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute product-tier RAG metrics from live Langfuse traffic.")
    parser.add_argument("--hours", type=float, default=24.0, help="Look-back window in hours (default 24).")
    args = parser.parse_args()

    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    metrics = compute_product_metrics(since)

    print(f"Product metrics for the last {args.hours}h ({metrics['window_start']} to {metrics['window_end']}):")
    print(f"  Total requests:          {metrics['total_requests']}")
    print(f"  Active users (sessions): {metrics['active_users']}")
    print(
        f"  Auto-resolution rate:    {_pct(metrics['auto_resolution_rate'])} "
        f"({metrics['resolved_requests']}/{metrics['total_requests']})"
    )
    print(
        f"  Exclusion rate:          {_pct(metrics['exclusion_rate'])} "
        f"({metrics['excluded_requests']}/{metrics['total_requests']})"
    )
    print(
        f"  Error rate:              {_pct(metrics['error_rate'])} "
        f"({metrics['errored_requests']}/{metrics['total_requests']})"
    )
    print(f"  Feedback:                {metrics['feedback_up']} up / {metrics['feedback_down']} down")
    print(f"  CSAT proxy (thumbs-up ratio): {_pct(metrics['csat_proxy'])}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
