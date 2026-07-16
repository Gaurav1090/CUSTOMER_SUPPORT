"""PII redaction.

Two layers, applied together:
- Regex, for structured PII: emails, phone numbers, card-like numbers.
- NER via Presidio (spaCy en_core_web_sm under the hood), for unstructured
  PII regex can't catch: names, locations.

Applied at two separate exposure surfaces -- see the architecture punch
list's PII/governance item:
- Ingestion (data_ingestion/ingestion_pipeline.py): source documents
  (reviews, PDF text) before they're chunked and embedded.
- The live chat path (utils/ops.py): question/answer text before it's
  sent to Langfuse, which otherwise stores it indefinitely with no
  retention policy (unlike SessionStore's 24h TTL).

Deliberately a hard requirement in requirements.txt, not
requirements-optional.txt -- a silently-skipped security control is worse
than a missing feature. See utils/ops.py's Redis lesson from earlier this
same rollout: requirements-optional.txt was never installed in the Docker
image, so infra looked fully wired while the actual protection silently
never ran.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Loosely phone-shaped: an optional country code, then digit groups
# separated by spaces/dashes/dots/parens, at least 9 digits total. Requires
# actual phone-like grouping (not just any 9+ digit run) so this doesn't
# false-positive on things like product model numbers ("235v2") or ratings
# ("4.5") that show up constantly in this app's own review/product data.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{3,4}(?!\d)"
)

# 13-19 digits, optionally grouped by spaces/dashes -- format-based only,
# no Luhn check. Deliberately broad (better to over-redact a false positive
# in review text than miss a real card number).
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

_analyzer = None
_analyzer_load_failed = False


def _get_presidio_analyzer():
    """Lazily build a single shared Presidio AnalyzerEngine for the process
    lifetime -- constructing this per-call would reload the underlying
    spaCy model every time, the same per-request-instantiation mistake
    documented elsewhere in utils/ops.py. Configured to use en_core_web_sm
    explicitly; Presidio's default NLP engine config expects the much
    larger en_core_web_lg, which is unnecessary weight for this app's
    review/chat text and too large to want baked into the container image."""
    global _analyzer, _analyzer_load_failed
    if _analyzer is not None or _analyzer_load_failed:
        return _analyzer
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
        )
        _analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
        logger.info("Presidio PII analyzer loaded (en_core_web_sm).")
    except Exception:
        logger.exception("Failed to load Presidio PII analyzer; falling back to regex-only redaction.")
        _analyzer_load_failed = True
    return _analyzer


def _redact_regex(text: str) -> str:
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = _CARD_RE.sub("[REDACTED_CARD]", text)
    return text


def _redact_ner(text: str) -> str:
    analyzer = _get_presidio_analyzer()
    if analyzer is None or not text:
        return text
    try:
        results = analyzer.analyze(text=text, entities=["PERSON", "LOCATION"], language="en")
        # Replace right-to-left so earlier match offsets stay valid as the
        # string's length changes from replacements already applied.
        for result in sorted(results, key=lambda r: r.start, reverse=True):
            label = f"[REDACTED_{result.entity_type}]"
            text = text[: result.start] + label + text[result.end :]
        return text
    except Exception:
        logger.exception("Presidio NER redaction failed; returning regex-only redaction for this text.")
        return text


def redact_pii(text: Optional[str]) -> Optional[str]:
    """Redact emails/phone numbers/card-like numbers (regex) and
    names/locations (NER) from text. None/empty input passes through
    unchanged. NER redaction runs after regex so it only has to look at
    already-shorter text, and so a NER failure still leaves the regex
    pass's protection intact."""
    if not text:
        return text
    text = _redact_regex(text)
    text = _redact_ner(text)
    return text
