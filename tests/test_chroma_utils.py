import unittest
from unittest.mock import MagicMock, patch

from utils.chroma_utils import create_chroma_store


class ChromaStoreTests(unittest.TestCase):
    @patch("utils.chroma_utils.Chroma")
    def test_falls_back_to_local_when_cloud_credentials_missing(self, mock_chroma):
        mock_chroma.return_value = MagicMock()

        create_chroma_store(
            collection_name="demo",
            embedding_function=MagicMock(),
            chroma_api_key=None,
            chroma_tenant=None,
            chroma_database=None,
            persist_directory="/tmp/chroma_test",
        )

        kwargs = mock_chroma.call_args.kwargs
        self.assertIn("persist_directory", kwargs)
        self.assertEqual(kwargs["persist_directory"], "/tmp/chroma_test")
        self.assertNotIn("chroma_cloud_api_key", kwargs)
        self.assertNotIn("tenant", kwargs)
        self.assertNotIn("database", kwargs)

    @patch("utils.chroma_utils.Chroma")
    def test_cloud_mode_does_not_use_local_persistence(self, mock_chroma):
        mock_chroma.return_value = MagicMock()

        create_chroma_store(
            collection_name="demo",
            embedding_function=MagicMock(),
            chroma_api_key="key",
            chroma_tenant="tenant",
            chroma_database="db",
            persist_directory="/tmp/chroma_test",
            storage_mode="cloud",
        )

        kwargs = mock_chroma.call_args.kwargs
        self.assertNotIn("persist_directory", kwargs)
        self.assertEqual(kwargs["chroma_cloud_api_key"], "key")
        self.assertEqual(kwargs["tenant"], "tenant")
        self.assertEqual(kwargs["database"], "db")


if __name__ == "__main__":
    unittest.main()
