"""Construct the local analysis client used by the application."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from src.contracts import AnalysisClient
from src.ui.local_analysis_client import LocalAnalysisClient


def get_analysis_client() -> AnalysisClient:
    """Return the combined local message and URL analysis client."""
    load_dotenv()
    url_model_path = os.getenv("SAFEMATE_URL_MODEL_PATH") or None
    url_model_kind = os.getenv("SAFEMATE_URL_MODEL_KIND", "char").strip() or "char"
    return LocalAnalysisClient(
        url_model_path=url_model_path,
        url_model_kind=url_model_kind,
    )
