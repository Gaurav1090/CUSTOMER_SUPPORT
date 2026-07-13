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
        Load and return the embedding model.
        """
        try:
            provider = self.config["embedding_model"]["provider"]
            model_name=self.config["embedding_model"]["model_name"]

            if provider == "google":
                from langchain_google_genai import GoogleGenerativeAIEmbeddings

                self._get_required_env(["GOOGLE_API_KEY"])
                logger.info("Loading Google embedding model: %s", model_name)
                return GoogleGenerativeAIEmbeddings(model=model_name)

            if provider == "huggingface":
                from langchain_huggingface import HuggingFaceEmbeddings

                logger.info("Loading HuggingFace embedding model: %s", model_name)
                return HuggingFaceEmbeddings(model_name=model_name)

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
        """
        try:
            provider = os.getenv("LLM_PROVIDER", self.config["llm"]["provider"])
            model_name = model_name or os.getenv("LLM_MODEL_NAME") or self.config["llm"]["model_name"]
            logger.info("Loading LLM provider=%s model=%s", provider, model_name)

            if provider == "groq":
                env = self._get_required_env(["GROQ_API_KEY"])
                return ChatGroq(model=model_name, api_key=env["GROQ_API_KEY"])

            if provider == "google":
                from langchain_google_genai import ChatGoogleGenerativeAI

                self._get_required_env(["GOOGLE_API_KEY"])
                return ChatGoogleGenerativeAI(model=model_name)

            if provider == "huggingface":
                from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

                env = self._get_required_env(["HF_TOKEN"])
                endpoint = HuggingFaceEndpoint(
                    repo_id=model_name,
                    task="text-generation",
                    huggingfacehub_api_token=env["HF_TOKEN"],
                )
                return ChatHuggingFace(llm=endpoint)

            raise ValueError(f"Unsupported LLM provider: {provider}")
        except Exception as exc:
            raise RuntimeError("Failed to load LLM model.") from exc
