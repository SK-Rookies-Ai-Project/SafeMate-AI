import unittest
from unittest.mock import patch

from src.client_factory import get_analysis_client
from src.ui.local_analysis_client import LocalAnalysisClient


class AnalysisClientFactoryTest(unittest.TestCase):
    def test_builds_combined_local_client_by_default(self) -> None:
        with patch("src.client_factory.load_dotenv"), patch.dict(
            "os.environ", {}, clear=True
        ):
            client = get_analysis_client()

        self.assertIsInstance(client, LocalAnalysisClient)
        self.assertIsNone(client.url_model_path)
        self.assertEqual(client.url_model_kind, "char")

    def test_applies_url_model_configuration(self) -> None:
        with patch("src.client_factory.load_dotenv"), patch.dict(
            "os.environ",
            {
                "SAFEMATE_URL_MODEL_PATH": "models/custom-url.joblib",
                "SAFEMATE_URL_MODEL_KIND": " tfidf ",
            },
            clear=True,
        ):
            client = get_analysis_client()

        self.assertIsInstance(client, LocalAnalysisClient)
        self.assertEqual(client.url_model_path, "models/custom-url.joblib")
        self.assertEqual(client.url_model_kind, "tfidf")


if __name__ == "__main__":
    unittest.main()
