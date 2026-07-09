import os
import logging
from typing import List
from langchain_core.documents import Document
from utils.chroma_utils import create_chroma_store
from utils.config_loader import load_config
from utils.model_loader import ModelLoader
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class Retriever:
    
    def __init__(self):
        self.model_loader=ModelLoader()
        self.config=load_config()
        self._load_env_variables()
        self.vstore = None
        self.retriever = None
    
    def _load_env_variables(self):
         
        load_dotenv()

        required_vars = []
        if self.config["embedding_model"]["provider"] == "google":
            required_vars.append("GOOGLE_API_KEY")
        
        missing_vars = [var for var in required_vars if os.getenv(var) is None]
        
        if missing_vars:
            raise EnvironmentError(f"Missing environment variables: {missing_vars}")

        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        self.chroma_api_key = os.getenv("CHROMA_API_KEY")
        self.chroma_tenant = os.getenv("CHROMA_TENANT")
        self.chroma_database = os.getenv("CHROMA_DATABASE")
        
    
    def load_retriever(self):
        try:
            if not self.vstore:
                self.vstore = create_chroma_store(
                    collection_name=self.config["chroma"]["collection_name"],
                    embedding_function=self.model_loader.load_embeddings(),
                    chroma_api_key=self.chroma_api_key,
                    chroma_tenant=self.chroma_tenant,
                    chroma_database=self.chroma_database,
                    persist_directory=os.path.join(os.getcwd(), "chroma_db"),
                    storage_mode=os.getenv("CHROMA_STORAGE_MODE", "auto"),
                )
            if not self.retriever:
                top_k = self.config["retriever"]["top_k"] if "retriever" in self.config else 3
                self.retriever = self.vstore.as_retriever(search_kwargs={"k": top_k})
                logger.info("Retriever loaded successfully with top_k=%s.", top_k)
            return self.retriever
        except Exception as exc:
            raise RuntimeError("Failed to load Chroma retriever.") from exc
   

    
    def call_retriever(self,query:str)-> List[Document]:
        try:
            retriever=self.load_retriever()
            output=retriever.invoke(query)
            return output
        except Exception as exc:
            raise RuntimeError("Failed to retrieve relevant documents.") from exc
        
    
if __name__=='__main__':
    retriever_obj = Retriever()
    user_query = "Can you suggest good budget laptops?"
    results = retriever_obj.call_retriever(user_query)

    for idx, doc in enumerate(results, 1):
        print(f"Result {idx}: {doc.page_content}\nMetadata: {doc.metadata}\n")
