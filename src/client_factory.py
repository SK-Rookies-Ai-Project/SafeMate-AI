"""Select the configured analysis client implementation."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from src.contracts import AnalysisClient
from src.ui.local_url_client import LocalUrlAnalysisClient
from src.ui.mock_client import MockAnalysisClient


class AnalysisBackendConfigurationError(RuntimeError):
    """Raised when the configured analysis backend is unavailable."""


def get_analysis_client() -> AnalysisClient:
    """Return the configured analysis client without silent fallback."""
    load_dotenv()
    backend = os.getenv("SAFEMATE_ANALYSIS_BACKEND", "mock").strip().lower()
    if backend == "mock":
        return MockAnalysisClient()
    if backend == "local_url":
        model_path = os.getenv("SAFEMATE_URL_MODEL_PATH") or None
        model_kind = os.getenv("SAFEMATE_URL_MODEL_KIND", "feature").strip() or "feature"
        return LocalUrlAnalysisClient(model_path=model_path, model_kind=model_kind)
    raise AnalysisBackendConfigurationError(
        f"지원하지 않는 분석 백엔드입니다: {backend or '(empty)'}"
    )
