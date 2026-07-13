import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from prompt_library.prompt import PROMPT_TEMPLATES

logger = logging.getLogger(__name__)

NO_HISTORY_SENTINEL = "No prior conversation."


def contextualize_query(question: str, chat_history: str, load_llm) -> str:
    """Rewrite a follow-up question into a standalone query using chat
    history, via a small/fast LLM. Skips the LLM call entirely when there's
    no history to resolve against (first turn of a session), and falls back
    to the raw question on any failure -- retrieval must never hard-fail
    because rewriting failed.

    `load_llm` is a zero-arg callable (not a pre-built LLM instance) so that
    a *loading* failure (missing API key, provider misconfigured) is caught
    by the same try/except as an *invocation* failure -- calling it inline
    as an argument expression would raise before this function's own error
    handling ever runs."""
    if not question or not question.strip():
        return question
    if not chat_history or chat_history.strip() == NO_HISTORY_SENTINEL:
        return question

    try:
        llm = load_llm()
        prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATES["query_contextualize"])
        chain = prompt | llm | StrOutputParser()
        rewritten = chain.invoke({"chat_history": chat_history, "question": question}).strip()
        return rewritten or question
    except Exception:
        logger.exception("Query contextualization failed; falling back to raw question.")
        return question
