import json
import logging
import os
import re
import secrets
import time
from typing import Optional

import anyio
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel

from langchain_core.prompts import ChatPromptTemplate

from retriever.retrieval import Retriever

from utils.model_loader import ModelLoader
from utils.ops import (
    RateLimiter,
    RequestTrace,
    ResponseCache,
    SessionStore,
    assign_experiment_variant,
    build_langfuse_trace,
    finish_langfuse_trace,
    finish_llm_generation,
    new_request_id,
    record_feedback_score,
    start_llm_generation,
)
from utils.pii import redact_pii
from utils.prompt_guard import detect_prompt_injection

from prompt_library.prompt import PROMPT_TEMPLATES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

INSUFFICIENT_CONTEXT_NO_DOCS = "Insufficient context. Please provide more details about the product or issue."
INSUFFICIENT_CONTEXT_UNGROUNDED = "Insufficient context. I cannot confidently answer from the retrieved evidence alone."
PROMPT_INJECTION_BLOCKED = "I can't process that request. Please ask a genuine product question."

load_dotenv()

app = FastAPI()


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory="templates")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8001,http://127.0.0.1:8001",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app_api_key = os.getenv("APP_API_KEY")

retriever_obj = Retriever()

model_loader = ModelLoader()
response_cache = ResponseCache()
rate_limiter = RateLimiter()
session_store = SessionStore()


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id", new_request_id())
    request.state.request_id = request_id

    protected_paths = {"/get", "/get/stream", "/feedback"}
    if request.url.path in protected_paths and request.method != "OPTIONS":
        if not app_api_key:
            logger.error("APP_API_KEY is not configured.")
            return PlainTextResponse(
                "Application authentication is not configured.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        request_api_key = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(request_api_key, app_api_key):
            return PlainTextResponse(
                "Invalid or missing API key.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        identity = request_api_key or (request.client.host if request.client else "unknown")
        if not rate_limiter.allow(identity):
            return PlainTextResponse(
                "Rate limit exceeded. Please slow down and try again shortly.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


def strip_reasoning_tokens(output: str) -> str:
    output = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL | re.IGNORECASE)
    output = re.sub(r"<think>.*", "", output, flags=re.DOTALL | re.IGNORECASE)
    return output.strip()


_CITATION_BRACKET_RE = re.compile(r"\s*\[source:[^\]]+\]")


def _strip_citations(answer: str) -> str:
    """Drop [source:ID] markers before an answer is replayed back into a
    future prompt as chat history. Otherwise a weaker model tends to copy a
    source ID forward from a *previous* turn's answer and cite it against
    the *current* turn's freshly retrieved (and likely different) context --
    a fabricated-looking citation that _verify_citations then correctly
    rejects, producing a false "Insufficient context" on a question the
    model could otherwise have answered fine from history."""
    return _CITATION_BRACKET_RE.sub("", answer)


def _build_chat_history(session_id: str) -> str:
    history = session_store.get_recent(session_id, limit=4)
    if not history:
        return "No prior conversation."
    return "\n".join(
        f"User: {item['user']}\nAssistant: {_strip_citations(item['assistant'])}" for item in history
    )


def _judge_groundedness(context: str, answer: str, langfuse_span=None) -> bool:
    judge_prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATES["grounding_judge"])
    llm = model_loader.load_llm()
    chain = judge_prompt | llm
    inputs = {"context": context, "answer": answer}
    model_name = os.getenv("LLM_MODEL_NAME") or model_loader.config["llm"]["model_name"]
    generation = start_llm_generation(langfuse_span, "groundedness_judge", model_name, input_data={"answer": answer})
    ai_message = chain.invoke(inputs)
    verdict = (ai_message.content or "").strip().upper()
    finish_llm_generation(generation, verdict, getattr(ai_message, "usage_metadata", None))
    return verdict == "YES"


def _build_context_text(retrieved_documents):
    # Delimited so the model can distinguish retrieved (untrusted,
    # user-generated) review text from its own instructions -- see the
    # product_bot prompt's injection-defense line.
    return "\n\n".join(
        f'<doc source="{doc.metadata.get("source_id", "unknown")}">{doc.page_content}</doc>'
        for doc in retrieved_documents
    )


def _source_ids(retrieved_documents):
    return [doc.metadata.get("source_id", "unknown") for doc in retrieved_documents]


# Matches each individual "source:ID" token rather than a whole [...]
# bracket, since some models (observed on Llama-3.3-70B-Instruct via the
# HuggingFace router) bundle several citations supporting one claim into a
# single bracket -- "[source:A, source:B]" -- instead of the one-per-bracket
# form the prompt asks for. Anchoring on the bracket pair alone would treat
# that whole bundled string as one fabricated ID and fail a fully-grounded
# answer.
_CITATION_RE = re.compile(r"source:\s*([^\],\s]+)")


def _verify_citations(answer: str, retrieved_documents) -> bool:
    """False only if the answer cites a source_id that wasn't actually
    retrieved -- a fabricated citation, and a stronger hallucination signal
    than the LLM groundedness judge alone. An answer with no citations at
    all isn't flagged here; that's the judge's job."""
    cited_ids = set(_CITATION_RE.findall(answer))
    if not cited_ids:
        return True
    valid_ids = set(_source_ids(retrieved_documents))
    return cited_ids.issubset(valid_ids)


def _embed_query(query: str):
    try:
        return model_loader.load_embeddings().embed_query(query)
    except Exception:
        logger.exception("Failed to embed query for semantic cache.")
        return None


def _ab_test_model_override(variant: str) -> Optional[str]:
    """The experiment model name when the A/B test is enabled and this
    request landed in the treatment bucket, None otherwise (use the
    normally-configured model, i.e. every control-variant and every
    request when the experiment is off). Opt-in and off by default --
    AB_TEST_ENABLED must be explicitly set, so this never silently starts
    spending on a second model."""
    if variant != "treatment":
        return None
    if os.getenv("AB_TEST_ENABLED", "false").strip().lower() != "true":
        return None
    return os.getenv("AB_TEST_MODEL_NAME") or None


def invoke_chain_details(query: str, session_id: str = "default", request_id: str = None):
    request_id = request_id or new_request_id()
    trace = RequestTrace(request_id=request_id, question=query, session_id=session_id)
    variant = assign_experiment_variant(session_id)
    trace.add("experiment_variant", variant)
    langfuse_trace = build_langfuse_trace(trace)

    try:
        injection_technique = detect_prompt_injection(query)
        if injection_technique:
            trace.add("prompt_injection_technique", injection_technique)
            trace.finish("blocked")
            finish_langfuse_trace(langfuse_trace, trace, output=PROMPT_INJECTION_BLOCKED)
            return {
                "answer": PROMPT_INJECTION_BLOCKED,
                "cache_hit": "blocked",
                "retrieved_documents": [],
                "request_id": request_id,
            }

        query_embedding = _embed_query(query)
        cached = response_cache.get_exact(query, session_id)
        if not cached and query_embedding:
            cached = response_cache.get_semantic(query, query_embedding, session_id)
        if cached:
            trace.add("cache_hit", cached.hit_type)
            trace.finish("ok")
            finish_langfuse_trace(langfuse_trace, trace, output=cached.answer)
            session_store.append(session_id, query, cached.answer)
            return {
                "answer": cached.answer,
                "cache_hit": cached.hit_type,
                "retrieved_documents": [],
                "request_id": request_id,
            }

        chat_history = _build_chat_history(session_id)

        retrieval_start = time.time()
        retrieved_documents = retriever_obj.call_retriever(query, chat_history=chat_history, langfuse_span=langfuse_trace)
        trace.add("retrieval_latency_ms", int((time.time() - retrieval_start) * 1000))
        trace.add("standalone_query", redact_pii(retriever_obj.last_standalone_query))
        trace.add("retrieved_source_ids", _source_ids(retrieved_documents))
        is_comparison = bool(retriever_obj.last_comparison_products)
        trace.add("comparison_products", retriever_obj.last_comparison_products)

        context_text = _build_context_text(retrieved_documents)
        prompt_key = "product_comparison_bot" if is_comparison else "product_bot"
        prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATES[prompt_key])
        ab_test_model = _ab_test_model_override(variant)
        if ab_test_model:
            llm = model_loader.load_llm(model_name=ab_test_model)
            resolved_model_name = ab_test_model
        else:
            llm = model_loader.load_llm()
            resolved_model_name = os.getenv("LLM_MODEL_NAME") or model_loader.config["llm"]["model_name"]

        chain = prompt | llm
        generation = start_llm_generation(
            langfuse_trace, "answer_generation", resolved_model_name, input_data={"question": query}
        )
        generation_start = time.time()
        ai_message = chain.invoke({"context": context_text, "question": query, "chat_history": chat_history})
        trace.add("generation_latency_ms", int((time.time() - generation_start) * 1000))
        output = ai_message.content if isinstance(ai_message.content, str) else str(ai_message.content)
        finish_llm_generation(generation, output, getattr(ai_message, "usage_metadata", None))
        output = strip_reasoning_tokens(output)

        citation_check = "skipped_no_context"
        groundedness_verdict = "skipped_no_context"
        if not retrieved_documents:
            output = INSUFFICIENT_CONTEXT_NO_DOCS
        else:
            citation_check = "passed" if _verify_citations(output, retrieved_documents) else "failed"
            if citation_check == "failed":
                output = INSUFFICIENT_CONTEXT_UNGROUNDED
                groundedness_verdict = "skipped_citation_failed"
            else:
                # redact_pii() runs a Presidio/spaCy NER pass, which has known
                # false positives on brand/product names (see utils/pii.py) --
                # too risky to apply to `output` itself, since that would
                # corrupt the answer actually shown to the user. Redact a
                # throwaway copy instead, just for this external judge call.
                groundedness_verdict = (
                    "passed"
                    if _judge_groundedness(context_text, redact_pii(output), langfuse_span=langfuse_trace)
                    else "failed"
                )
                if groundedness_verdict == "failed":
                    output = INSUFFICIENT_CONTEXT_UNGROUNDED
        trace.add("citation_check", citation_check)
        trace.add("groundedness_verdict", groundedness_verdict)

        # Don't cache a refusal -- citation/groundedness failures are often
        # transient (LLM sampling variance on retry), and caching one would
        # make it "sticky" for the full TTL: every repeat or paraphrase of
        # a genuinely answerable question would keep getting refused until
        # expiry, even though a fresh retry could well succeed.
        if output not in (INSUFFICIENT_CONTEXT_NO_DOCS, INSUFFICIENT_CONTEXT_UNGROUNDED):
            response_cache.set(query, session_id, output, query_embedding=query_embedding)
        session_store.append(session_id, query, output)
        trace.add("cache_hit", "miss")
        trace.finish("ok")
        finish_langfuse_trace(langfuse_trace, trace, output=output)
        return {
            "answer": output,
            "cache_hit": "miss",
            "retrieved_documents": retrieved_documents,
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        trace.finish("error", error=str(exc))
        finish_langfuse_trace(langfuse_trace, trace, error=str(exc))
        logger.exception("Failed to generate response.")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant could not process the request right now. Please try again later.",
        )


def invoke_chain(query: str, session_id: str = "default"):
    return invoke_chain_details(query, session_id=session_id)["answer"]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Render the chat interface.
    """
    return templates.TemplateResponse(request, "chat.html")


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    chroma_storage_mode = os.getenv("CHROMA_STORAGE_MODE", "auto").strip().lower()
    chroma_cloud_ready = all(
        [
            os.getenv("CHROMA_API_KEY"),
            os.getenv("CHROMA_TENANT"),
            os.getenv("CHROMA_DATABASE"),
        ]
    )
    chroma_local_ready = os.path.exists(os.path.join(BASE_DIR, "chroma_db"))
    chroma_ready = chroma_cloud_ready if chroma_storage_mode in {"cloud", "remote"} else chroma_local_ready or chroma_cloud_ready
    checks = {
        "app_api_key": bool(app_api_key),
        "groq_api_key": bool(os.getenv("GROQ_API_KEY")),
        "chroma_storage": chroma_ready,
    }
    status_code = status.HTTP_200_OK if all(checks.values()) else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse({"status": "ready" if status_code == 200 else "not_ready", "checks": checks}, status_code=status_code)


@app.post("/get", response_class=PlainTextResponse)
async def chat(request: Request, msg: str = Form(..., min_length=1, max_length=2000)):
    session_id = request.headers.get("X-Session-Id", "default")
    result = await anyio.to_thread.run_sync(
        lambda: invoke_chain_details(msg.strip(), session_id=session_id, request_id=request.state.request_id)
    )
    logger.info("Generated response for chat request.")
    return result["answer"]


@app.post("/get/stream")
async def chat_stream(request: Request, msg: str = Form(..., min_length=1, max_length=2000)):
    session_id = request.headers.get("X-Session-Id", "default")
    query = msg.strip()

    async def event_stream():
        yield f"event: request_id\ndata: {request.state.request_id}\n\n"
        yield "event: status\ndata: retrieving\n\n"
        result = await anyio.to_thread.run_sync(
            lambda: invoke_chain_details(query, session_id=session_id, request_id=request.state.request_id)
        )
        yield f"event: cache\ndata: {result['cache_hit']}\n\n"
        for token in result["answer"].split(" "):
            # json.dumps forces the payload onto a single physical line
            # (embedded newlines become the literal two-char escape \n,
            # not a real line break) -- SSE requires every physical line of
            # a "data:" field to carry its own "data:" prefix, which a bare
            # f"data: {token}" doesn't do for a token containing a real
            # newline. Markdown answers (headings, lists, tables) routinely
            # have those now; the naive form silently truncated everything
            # after the first embedded newline in both this generator and
            # chat.html's hand-rolled SSE parser.
            yield f"event: token\ndata: {json.dumps(token + ' ')}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class FeedbackRequest(BaseModel):
    request_id: str
    rating: str


@app.post("/feedback")
async def feedback(payload: FeedbackRequest):
    if payload.rating not in ("up", "down"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="rating must be 'up' or 'down'.")

    recorded = await anyio.to_thread.run_sync(lambda: record_feedback_score(payload.request_id, payload.rating))
    return {"recorded": recorded}
