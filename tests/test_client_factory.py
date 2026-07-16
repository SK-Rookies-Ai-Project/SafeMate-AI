import unittest
from unittest.mock import patch

from src.client_factory import (
    AnalysisBackendConfigurationError,
    get_analysis_client,
)
from src.ui.local_url_client import LocalUrlAnalysisClient
from src.ui.mock_client import MockAnalysisClient


class AnalysisClientFactoryTest(unittest.TestCase):
    def test_defaults_to_mock_backend(self) -> None:
        with patch("src.client_factory.load_dotenv"), patch.dict(
            "os.environ", {}, clear=True
        ):
            client = get_analysis_client()

        self.assertIsInstance(client, MockAnalysisClient)

    def test_normalizes_configured_backend(self) -> None:
        with patch("src.client_factory.load_dotenv"), patch.dict(
            "os.environ",
            {"SAFEMATE_ANALYSIS_BACKEND": "  MoCk  "},
            clear=True,
        ):
            client = get_analysis_client()

        self.assertIsInstance(client, MockAnalysisClient)

    def test_returns_local_url_backend(self) -> None:
        with patch("src.client_factory.load_dotenv"), patch.dict(
            "os.environ",
            {
                "SAFEMATE_ANALYSIS_BACKEND": "local_url",
                "SAFEMATE_URL_MODEL_PATH": "models/url_char_model.joblib",
            },
            clear=True,
        ):
            client = get_analysis_client()

        self.assertIsInstance(client, LocalUrlAnalysisClient)
        self.assertEqual(client.model_path, "models/url_char_model.joblib")

    def test_rejects_unavailable_backend_without_fallback(self) -> None:
        for backend in ("local", "api", ""):
            with self.subTest(backend=backend), patch(
                "src.client_factory.load_dotenv"
            ), patch.dict(
                "os.environ",
                {"SAFEMATE_ANALYSIS_BACKEND": backend},
                clear=True,
            ):
                with self.assertRaises(AnalysisBackendConfigurationError):
                    get_analysis_client()


if __name__ == "__main__":
    unittest.main()
