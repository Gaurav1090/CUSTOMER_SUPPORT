import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from prompt_library.prompt import PROMPT_TEMPLATES

logger = logging.getLogger(__name__)

NO_HISTORY_SENTINEL = "No prior conversation."


def contextualize_query(question: str, chat_history: str, llm) -> str:
    """Rewrite a follow-up question into a standalone query using chat
    history, via a small/fast LLM. Skips the LLM call entirely when there's
    no history to resolve against (first turn of a session), and falls back
    to the raw question on any failure -- retrieval must never hard-fail
    because rewriting failed."""
    if not question or not question.strip():
        return question
    if not chat_history or chat_history.strip() == NO_HISTORY_SENTINEL:
        return question

    try:
        prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATES["query_contextualize"])
        chain = prompt | llm | StrOutputParser()
        rewritten = chain.invoke({"chat_history": chat_history, "question": question}).strip()
        return rewritten or question
    except Exception:
        logger.exception("Query contextualization failed; falling back to raw question.")
        return question
