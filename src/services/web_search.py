"""OpenAI hosted Web Search tool configuration and result normalization."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


WEB_SEARCH_INCLUDE = "web_search_call.action.sources"
OFFICIAL_SOURCE_DOMAINS = (
    "kisa.or.kr",
    "boho.or.kr",
    "krcert.or.kr",
    "police.go.kr",
    "fss.or.kr",
    "privacy.go.kr",
    "pipc.go.kr",
    "ncsc.go.kr",
    "msit.go.kr",
    "gov.kr",
    "korea.kr",
)


def build_web_search_tool(
    allowed_domains: tuple[str, ...] = OFFICIAL_SOURCE_DOMAINS,
) -> dict:
    """Return Web Search restricted to reviewed official-source domains."""
    normalized_domains = _normalize_allowed_domains(allowed_domains)
    if not normalized_domains:
        raise ValueError("공식 출처 도메인이 하나 이상 필요합니다.")
    return {
        "type": "web_search",
        "filters": {"allowed_domains": normalized_domains},
    }


def is_official_source_url(
    value: object,
    allowed_domains: tuple[str, ...] = OFFICIAL_SOURCE_DOMAINS,
) -> bool:
    """Return whether a URL is HTTPS and belongs to an approved domain."""
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return False
    normalized_hostname = _normalize_domain(hostname)
    return any(
        normalized_hostname == domain
        or normalized_hostname.endswith("." + domain)
        for domain in _normalize_allowed_domains(allowed_domains)
    )


def is_web_search_call(item: Any) -> bool:
    """Return whether a response output item is a Web Search call."""
    return _get_value(item, "type") == "web_search_call"


def normalize_web_citation(annotation: Any) -> dict | None:
    """Normalize a Responses API URL citation for the Streamlit UI."""
    if _get_value(annotation, "type") != "url_citation":
        return None
    url = _get_value(annotation, "url")
    if not is_official_source_url(url):
        return None
    normalized_url = url.strip()
    return {
        "type": "url",
        "title": _get_value(annotation, "title") or normalized_url,
        "url": normalized_url,
    }


def _normalize_allowed_domains(domains: tuple[str, ...]) -> list[str]:
    return list(
        dict.fromkeys(
            _normalize_domain(domain) for domain in domains if domain.strip()
        )
    )


def _normalize_domain(domain: str) -> str:
    normalized = domain.strip().rstrip(".").lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return normalized


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
