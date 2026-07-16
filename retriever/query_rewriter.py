import logging
from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate

from prompt_library.prompt import PROMPT_TEMPLATES
from utils.ops import finish_llm_generation, start_llm_generation

logger = logging.getLogger(__name__)

NO_HISTORY_SENTINEL = "No prior conversation."
_PRODUCT_LINE_PREFIX = "PRODUCT:"


def contextualize_query(question: str, chat_history: str, load_llm, langfuse_span=None, model_name=None) -> str:
    """Rewrite a follow-up question into a standalone query using chat
    history, via a small/fast LLM. Skips the LLM call entirely when there's
    no history to resolve against (first turn of a session), and falls back
    to the raw question on any failure -- retrieval must never hard-fail
    because rewriting failed.

    `load_llm` is a zero-arg callable (not a pre-built LLM instance) so that
    a *loading* failure (missing API key, provider misconfigured) is caught
    by the same try/except as an *invocation* failure -- calling it inline
    as an argument expression would raise before this function's own error
    handling ever runs.

    `langfuse_span`/`model_name` are optional -- when the caller has a live
    Langfuse trace, this records the rewrite step as its own nested
    generation observation (model + token usage), so Langfuse's cost
    dashboard can attribute cost to the rewrite step separately from the
    main answer generation."""
    if not question or not question.strip():
        return question
    if not chat_history or chat_history.strip() == NO_HISTORY_SENTINEL:
        return question

    generation = None
    try:
        llm = load_llm()
        prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATES["query_contextualize"])
        chain = prompt | llm
        inputs = {"chat_history": chat_history, "question": question}
        generation = start_llm_generation(langfuse_span, "query_rewrite", model_name, input_data=inputs)
        ai_message = chain.invoke(inputs)
        rewritten = (ai_message.content or "").strip()
        finish_llm_generation(generation, rewritten, getattr(ai_message, "usage_metadata", None))
        return rewritten or question
    except Exception:
        logger.exception("Query contextualization failed; falling back to raw question.")
        finish_llm_generation(generation, None, None)
        return question


def classify_comparison_products(question: str, load_llm, langfuse_span=None, model_name=None) -> Optional[List[str]]:
    """Detect whether `question` is asking to compare 2+ specific named
    products, via a small/fast LLM (same rewrite model as
    contextualize_query, not a separate provider call). Returns the
    extracted product names when it's a genuine multi-product comparison
    (2 or more), None otherwise -- including on any failure, since
    retrieval must never hard-fail because classification failed; a
    missed comparison just falls back to normal single-query retrieval,
    which is the existing, already-working behavior.

    A structured "PRODUCT: <name>" line-per-product format is used instead
    of asking for JSON -- far more reliable to parse out of a small model's
    output than balanced JSON syntax, and trivial to validate (a response
    with fewer than 2 PRODUCT: lines is treated as "not a comparison")."""
    if not question or not question.strip():
        return None

    generation = None
    try:
        llm = load_llm()
        prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATES["comparison_classifier"])
        chain = prompt | llm
        inputs = {"question": question}
        generation = start_llm_generation(langfuse_span, "comparison_classification", model_name, input_data=inputs)
        ai_message = chain.invoke(inputs)
        raw = (ai_message.content or "").strip()
        finish_llm_generation(generation, raw, getattr(ai_message, "usage_metadata", None))

        products = [
            line.strip()[len(_PRODUCT_LINE_PREFIX):].strip()
            for line in raw.splitlines()
            if line.strip().upper().startswith(_PRODUCT_LINE_PREFIX)
        ]
        products = [product for product in products if product]
        return products if len(products) >= 2 else None
    except Exception:
        logger.exception("Comparison classification failed; treating as a normal (non-comparison) query.")
        finish_llm_generation(generation, None, None)
        return None
