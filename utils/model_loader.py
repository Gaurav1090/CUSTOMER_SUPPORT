import os
import logging

from dotenv import load_dotenv
from utils.config_loader import load_config
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

class ModelLoader:
    """
    A utility class to load embedding models and LLM models.
    """
    def __init__(self):
        load_dotenv()
        self.config=load_config()
        self._embeddings = None
        self._llm_cache = {}

    def _get_required_env(self, required_vars):
        """
        Validate necessary environment variables.
        """
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise EnvironmentError(f"Missing environment variables: {missing_vars}")
        return {var: os.getenv(var) for var in required_vars}

    def load_embeddings(self):
        """
        Load and return the embedding model. Cached on this instance --
        reconstructing HuggingFaceEmbeddings reloads the sentence-transformer
        weights from disk every time (measured ~5.6-7.4s per call vs ~7ms
        reused), and this is called unconditionally on every chat request
        via main.py's _embed_query, so an uncached call site here was the
        single largest recurring latency cost found during testing.
        """
        if self._embeddings is not None:
            return self._embeddings

        try:
            provider = self.config["embedding_model"]["provider"]
            model_name=self.config["embedding_model"]["model_name"]

            if provider == "google":
                from langchain_google_genai import GoogleGenerativeAIEmbeddings

                self._get_required_env(["GOOGLE_API_KEY"])
                logger.info("Loading Google embedding model: %s", model_name)
                self._embeddings = GoogleGenerativeAIEmbeddings(model=model_name)
                return self._embeddings

            if provider == "huggingface":
                from langchain_huggingface import HuggingFaceEmbeddings

                logger.info("Loading HuggingFace embedding model: %s", model_name)
                self._embeddings = HuggingFaceEmbeddings(model_name=model_name)
                return self._embeddings

            raise ValueError(f"Unsupported embedding provider: {provider}")
        except Exception as exc:
            raise RuntimeError("Failed to load embedding model.") from exc

    def load_llm(self, model_name: str = None):
        """
        Load and return the LLM model. Pass model_name to override the
        configured generation model, e.g. for a cheaper/faster model used
        for query rewriting rather than final answer generation.

        LLM_PROVIDER / LLM_MODEL_NAME env vars take precedence over
        config.yaml when set, so switching providers (e.g. after hitting a
        rate limit) is a one-line env change instead of an edit + redeploy.
        model_name passed explicitly by the caller still wins over
        LLM_MODEL_NAME -- that path is for the distinct rewrite model, not
        the main generation model this env var is meant to override.

        Cached per (provider, model_name) on this instance -- main.py calls
        this twice per request (generation + groundedness judge) with the
        same default model, and each call was constructing its own client.
        """
        provider = os.getenv("LLM_PROVIDER", self.config["llm"]["provider"])
        model_name = model_name or os.getenv("LLM_MODEL_NAME") or self.config["llm"]["model_name"]
        cache_key = (provider, model_name)
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]

        try:
            logger.info("Loading LLM provider=%s model=%s", provider, model_name)

            # temperature=0 on every provider -- same question + same
            # retrieved context should give the same answer. Found via
            # testing: identical questions asked twice in one session
            # produced meaningfully different answers (different products
            # emphasized) with no temperature set, which defaults to
            # sampling with randomness on all three providers.
            if provider == "groq":
                env = self._get_required_env(["GROQ_API_KEY"])
                llm = ChatGroq(model=model_name, api_key=env["GROQ_API_KEY"], temperature=0)

            elif provider == "google":
                from langchain_google_genai import ChatGoogleGenerativeAI

                self._get_required_env(["GOOGLE_API_KEY"])
                llm = ChatGoogleGenerativeAI(model=model_name, temperature=0)

            elif provider == "huggingface":
                from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

                env = self._get_required_env(["HF_TOKEN"])
                endpoint = HuggingFaceEndpoint(
                    repo_id=model_name,
                    task="text-generation",
                    huggingfacehub_api_token=env["HF_TOKEN"],
                    temperature=None,
                    do_sample=False,
                )
                llm = ChatHuggingFace(llm=endpoint)

            else:
                raise ValueError(f"Unsupported LLM provider: {provider}")

            self._llm_cache[cache_key] = llm
            return llm
        except Exception as exc:
            raise RuntimeError("Failed to load LLM model.") from exc
