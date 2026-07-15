"""OpenAI hosted Web Search tool configuration and result normalization."""

from __future__ import annotations

from typing import Any


WEB_SEARCH_INCLUDE = "web_search_call.action.sources"


def build_web_search_tool() -> dict:
    """Return the Responses API hosted Web Search tool configuration."""
    return {"type": "web_search"}


def is_web_search_call(item: Any) -> bool:
    """Return whether a response output item is a Web Search call."""
    return _get_value(item, "type") == "web_search_call"


def normalize_web_citation(annotation: Any) -> dict | None:
    """Normalize a Responses API URL citation for the Streamlit UI."""
    if _get_value(annotation, "type") != "url_citation":
        return None
    url = _get_value(annotation, "url")
    if not isinstance(url, str) or not url.strip():
        return None
    normalized_url = url.strip()
    return {
        "type": "url",
        "title": _get_value(annotation, "title") or normalized_url,
        "url": normalized_url,
    }


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
