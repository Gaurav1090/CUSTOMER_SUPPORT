import os
import pandas as pd
from dotenv import load_dotenv
from typing import List
from langchain_core.documents import Document
from utils.chroma_utils import create_chroma_store
from utils.model_loader import ModelLoader
from utils.config_loader import load_config

class DataIngestion:
    """
    Class to handle data transformation and ingestion into Chroma vector store.
    """

    def __init__(self):
        """
        Initialize environment variables, embedding model, and set CSV file path.
        """
        print("Initializing DataIngestion pipeline...")
        self.config=load_config()
        self.model_loader=ModelLoader()
        self._load_env_variables()
        self.csv_path = self._get_csv_path()
        self.product_data = self._load_csv()

    def _load_env_variables(self):
        """
        Load optional environment variables.
        """
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

    def _get_csv_path(self):
        """
        Get path to the CSV file located inside 'data' folder.
        """
        current_dir = os.getcwd()
        csv_path = os.path.join(current_dir, 'data', 'flipkart_product_review.csv')

        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found at: {csv_path}")

        return csv_path

    def _load_csv(self):
        """
        Load product data from CSV.
        """
        df = pd.read_csv(self.csv_path)
        expected_columns = {'product_title', 'rating', 'summary', 'review'}

        if not expected_columns.issubset(set(df.columns)):
            raise ValueError(f"CSV must contain columns: {expected_columns}")

        return df

    def transform_data(self):
        """
        Transform product data into list of LangChain Document objects.
        """
        product_list = []

        for _, row in self.product_data.iterrows():
            product_entry = {
                "product_name": row['product_title'],
                "product_rating": row['rating'],
                "product_summary": row['summary'],
                "product_review": row['review']
            }
            product_list.append(product_entry)

        documents = []
        for entry in product_list:
            metadata = {
                "product_name": entry["product_name"],
                "product_rating": entry["product_rating"],
                "product_summary": entry["product_summary"]
            }
            doc = Document(page_content=entry["product_review"], metadata=metadata)
            documents.append(doc)

        print(f"Transformed {len(documents)} documents.")
        return documents

    def store_in_vector_db(self, documents: List[Document]):
        """
        Store documents into Chroma vector store.
        """
        persist_directory = os.path.join(os.getcwd(), "chroma_db")
        vstore = create_chroma_store(
            collection_name=self.config["chroma"]["collection_name"],
            embedding_function=self.model_loader.load_embeddings(),
            chroma_api_key=self.chroma_api_key,
            chroma_tenant=self.chroma_tenant,
            chroma_database=self.chroma_database,
            persist_directory=persist_directory,
            storage_mode=os.getenv("CHROMA_STORAGE_MODE", "auto"),
        )
        try:
            inserted_ids = vstore.add_documents(documents)
        except Exception as exc:
            if "quota" not in str(exc).lower() and "rate limit" not in str(exc).lower():
                raise
            print("Cloud Chroma quota exceeded; retrying with local persistence.")
            vstore = create_chroma_store(
                collection_name=self.config["chroma"]["collection_name"],
                embedding_function=self.model_loader.load_embeddings(),
                chroma_api_key=None,
                chroma_tenant=None,
                chroma_database=None,
                persist_directory=persist_directory,
                storage_mode="local",
            )
            inserted_ids = vstore.add_documents(documents)

        print(f"Successfully inserted {len(inserted_ids)} documents into Chroma.")
        return vstore, inserted_ids

    def run_pipeline(self):
        """
        Run the full data ingestion pipeline: transform data and store into vector DB.
        """
        documents = self.transform_data()
        vstore, inserted_ids = self.store_in_vector_db(documents)

        # Optionally do a quick search
        query = "Can you tell me the low budget headphone?"
        results = vstore.similarity_search(query)

        print(f"\nSample search results for query: '{query}'")
        for res in results:
            print(f"Content: {res.page_content}\nMetadata: {res.metadata}\n")

# Run if this file is executed directly
if __name__ == "__main__":
    ingestion = DataIngestion()
    ingestion.run_pipeline()
