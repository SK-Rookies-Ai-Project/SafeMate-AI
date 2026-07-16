"""Shared analysis client and request contracts."""

from __future__ import annotations

import json
from typing import Protocol

from src.config import MAX_ANALYSIS_REQUEST_BYTES, MAX_URL_CANDIDATES


class AnalysisRequestValidationError(ValueError):
    """Raised before invalid analysis payloads reach a model or API."""


class AnalysisClient(Protocol):
    def analyze(self, payload: dict) -> dict:
        """Return an AnalysisResponse-compatible dictionary."""


def build_analysis_request(prepared_input: dict, request_id: str) -> dict:
    """Build a bounded JSON-compatible analysis request."""
    request = {
        "schema_version": "1.0",
        "request_id": request_id,
        "input_type": prepared_input["input_type"],
        "subject": prepared_input.get("subject"),
        "body": prepared_input["body"],
        "url_candidates": prepared_input.get("url_candidates", [])[
            :MAX_URL_CANDIDATES
        ],
    }
    request_size = len(
        json.dumps(
            request,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if request_size > MAX_ANALYSIS_REQUEST_BYTES:
        raise AnalysisRequestValidationError(
            "분석 요청 크기가 허용된 최대 크기를 초과했습니다."
        )
    return request
