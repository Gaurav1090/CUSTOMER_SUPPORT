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

    def load_llm(self):
        """
        Load and return the LLM model.
        """
        try:
            provider = self.config["llm"]["provider"]
            model_name=self.config["llm"]["model_name"]

            if provider != "groq":
                raise ValueError(f"Unsupported LLM provider: {provider}")

            env = self._get_required_env(["GROQ_API_KEY"])
            logger.info("Loading LLM provider=%s model=%s", provider, model_name)
            groq_model=ChatGroq(model=model_name,api_key=env["GROQ_API_KEY"])
            return groq_model
        except Exception as exc:
            raise RuntimeError("Failed to load LLM model.") from exc
