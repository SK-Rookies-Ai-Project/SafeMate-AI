"""Select the configured analysis client implementation."""

from __future__ import annotations

import os

from src.contracts import AnalysisClient
from src.ui.mock_client import MockAnalysisClient


class AnalysisBackendConfigurationError(RuntimeError):
    """Raised when the configured analysis backend is unavailable."""


def get_analysis_client() -> AnalysisClient:
    """Return the configured analysis client without silent fallback."""
    backend = os.getenv("SAFEMATE_ANALYSIS_BACKEND", "mock").strip().lower()
    if backend == "mock":
        return MockAnalysisClient()
    raise AnalysisBackendConfigurationError(
        f"지원하지 않는 분석 백엔드입니다: {backend or '(empty)'}"
    )
