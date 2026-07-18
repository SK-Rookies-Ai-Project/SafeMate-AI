"""OpenAI hosted File Search tool configuration and result normalization."""

from __future__ import annotations

from typing import Any


FILE_SEARCH_INCLUDE = "file_search_call.results"


def build_file_search_tool(
    vector_store_id: str,
    *,
    max_num_results: int = 5,
) -> dict:
    """Return the Responses API hosted File Search tool configuration."""
    normalized_store_id = vector_store_id.strip()
    if not normalized_store_id:
        raise ValueError("Vector Store ID가 필요합니다.")
    return {
        "type": "file_search",
        "vector_store_ids": [normalized_store_id],
        "max_num_results": max_num_results,
    }


def is_file_search_call(item: Any) -> bool:
    """Return whether a response output item is a File Search call."""
    return _get_value(item, "type") == "file_search_call"


def normalize_file_citation(annotation: Any) -> dict | None:
    """Normalize a Responses API file citation for the Streamlit UI."""
    if _get_value(annotation, "type") != "file_citation":
        return None
    filename = _get_value(annotation, "filename") or "등록된 보안 문서"
    citation = {"type": "file", "title": str(filename)}
    file_id = _get_value(annotation, "file_id")
    if file_id:
        citation["file_id"] = str(file_id)
    return citation


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
