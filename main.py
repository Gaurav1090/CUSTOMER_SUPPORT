import logging
import os
import re
import secrets

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from langchain_core.runnables import RunnablePassthrough

from langchain_core.output_parsers import StrOutputParser

from langchain_core.prompts import ChatPromptTemplate

from retriever.retrieval import Retriever

from utils.model_loader import ModelLoader

from prompt_library.prompt import PROMPT_TEMPLATES

logger = logging.getLogger(__name__)

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


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    protected_paths = {"/get"}
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

    return await call_next(request)


def strip_reasoning_tokens(output: str) -> str:
    output = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL | re.IGNORECASE)
    output = re.sub(r"<think>.*", "", output, flags=re.DOTALL | re.IGNORECASE)
    return output.strip()


def invoke_chain(query: str):
    try:
        retriever = retriever_obj.load_retriever()
        prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATES["product_bot"])
        llm = model_loader.load_llm()

        chain = (
            {"context": retriever, "question": RunnablePassthrough()}
            | prompt
            | llm
            | StrOutputParser()
        )

        output = chain.invoke(query)
        return strip_reasoning_tokens(output)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to generate response.")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant could not process the request right now. Please try again later.",
        )

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Render the chat interface.
    """
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/get", response_class=PlainTextResponse)
async def chat(msg: str = Form(..., min_length=1, max_length=2000)):
    result = invoke_chain(msg.strip())
    logger.info("Generated response for chat request.")
    return result
