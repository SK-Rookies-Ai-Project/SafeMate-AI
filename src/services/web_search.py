"""OpenAI hosted Web Search configuration and strict evidence admission."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

WEB_SEARCH_INCLUDE = "web_search_call.action.sources"
MAX_RESPONSE_OUTPUT_ITEMS = 16
MAX_RESPONSE_CONTENT_PARTS = 8
MAX_RESPONSE_ANNOTATIONS = 32
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
    return {"type": "web_search", "filters": {"allowed_domains": normalized_domains}}


def canonicalize_official_url(
    value: object,
    allowed_domains: tuple[str, ...] = OFFICIAL_SOURCE_DOMAINS,
) -> str | None:
    """Return a network-free canonical official HTTPS URL, or ``None``.

    This deliberately does not fetch, resolve, or follow redirects.  The path,
    query, and fragment remain significant so a citation can only bind to the
    exact URL returned by the completed hosted call.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    normalized_hostname = _normalize_hostname(hostname)
    if not any(
        normalized_hostname == domain or normalized_hostname.endswith("." + domain)
        for domain in _normalize_allowed_domains(allowed_domains)
    ):
        return None
    path = parsed.path or "/"
    return urlunsplit(("https", normalized_hostname, path, parsed.query, parsed.fragment))


def is_official_source_url(
    value: object,
    allowed_domains: tuple[str, ...] = OFFICIAL_SOURCE_DOMAINS,
) -> bool:
    """Return whether a URL is HTTPS and belongs to an approved domain."""
    return canonicalize_official_url(value, allowed_domains) is not None


def is_web_search_call(item: Any) -> bool:
    """Return whether a response output item is a Web Search call."""
    return _get_value(item, "type") == "web_search_call"


def normalize_web_citation(annotation: Any) -> dict | None:
    """Normalize a standalone Responses API URL citation for legacy callers."""
    if _get_value(annotation, "type") != "url_citation":
        return None
    url = canonicalize_official_url(_get_value(annotation, "url"))
    if url is None:
        return None
    return {"type": "url", "title": _get_value(annotation, "title") or url, "url": url}


def admit_web_citations(
    output_text: str,
    claims: list[dict],
    output: list[Any],
    response_scope: str,
) -> list[dict] | None:
    """Admit bound Web citations or reject the entire Web evidence set.

    Every provider annotation must cite one unambiguous claim range and exactly
    one URL in a completed included Web Search call.  ``None`` is a global
    rejection; an empty list means that no Web annotation was present.
    """
    if not _is_scope(response_scope) or not isinstance(output_text, str):
        return None
    if not isinstance(output, list) or len(output) > MAX_RESPONSE_OUTPUT_ITEMS:
        return None
    annotations = _output_text_annotations(output)
    if annotations is None or len(annotations) > MAX_RESPONSE_ANNOTATIONS:
        return None
    claim_ranges = _claim_ranges(output_text, claims)
    if claim_ranges is None:
        return None
    source_urls = _completed_source_urls(output)
    if source_urls is None:
        return None

    citations: list[dict] = []
    for annotation_ordinal, annotation in enumerate(annotations):
        if _get_value(annotation, "type") != "url_citation":
            continue
        url = canonicalize_official_url(_get_value(annotation, "url"))
        start = _get_value(annotation, "start_index")
        end = _get_value(annotation, "end_index")
        if (
            url is None
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or end > len(output_text)
        ):
            return None
        bound_claims = [
            item for item in claim_ranges
            if item[1] <= start and end <= item[2]
        ]
        source_matches = [item for item in source_urls if item[0] == url]
        if len(bound_claims) != 1 or len(source_matches) != 1:
            return None
        citations.append(
            {
                "evidence_id": f"web:{response_scope}:{source_matches[0][1]}:{annotation_ordinal}",
                "type": "url",
                "title": _safe_title(_get_value(annotation, "title"), url),
                "url": url,
                "claim_ordinal": bound_claims[0][0],
            }
        )
    return citations


def _output_text_annotations(output: list[Any]) -> list[Any] | None:
    annotation_parts: list[list[Any]] = []
    total_parts = 0
    for item in output:
        if _get_value(item, "type") != "message":
            continue
        content = _get_value(item, "content", [])
        if not isinstance(content, list):
            return None
        total_parts += len(content)
        if total_parts > MAX_RESPONSE_CONTENT_PARTS:
            return None
        for part in content:
            if _get_value(part, "type") != "output_text":
                continue
            annotations = _get_value(part, "annotations", [])
            if not isinstance(annotations, list):
                return None
            annotation_parts.append(annotations)
    # Annotation offsets have one coordinate system: one provider output-text part.
    if len(annotation_parts) > 1:
        return None
    return annotation_parts[0] if annotation_parts else []


def _claim_ranges(output_text: str, claims: list[dict]) -> list[tuple[int, int, int]] | None:
    if not isinstance(claims, list) or len(claims) > 5:
        return None
    ranges: list[tuple[int, int, int]] = []
    for ordinal, claim in enumerate(claims):
        text = _get_value(claim, "text", _get_value(claim, "claim"))
        if not isinstance(text, str) or not text:
            return None
        # Response offsets address JSON text, so bind against the escaped literal.
        encoded = json.dumps(text, ensure_ascii=False)[1:-1]
        if not encoded or len(encoded) > len(output_text):
            return None
        start = output_text.find(encoded)
        if start < 0 or output_text.find(encoded, start + 1) >= 0:
            return None
        ranges.append((ordinal, start, start + len(encoded)))
    return ranges


def _completed_source_urls(output: list[Any]) -> list[tuple[str, int]] | None:
    urls: list[tuple[str, int]] = []
    for call_ordinal, item in enumerate(output):
        if not is_web_search_call(item):
            continue
        if _get_value(item, "status") != "completed":
            continue
        action = _get_value(item, "action")
        sources = _get_value(action, "sources") if action is not None else _get_value(item, "sources")
        if not isinstance(sources, list):
            return None
        for source in sources:
            url = canonicalize_official_url(_get_value(source, "url", _get_value(source, "source_url")))
            if url is None:
                return None
            urls.append((url, call_ordinal))
    return urls


def _safe_title(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _is_scope(value: object) -> bool:
    return isinstance(value, str) and len(value) == 24 and all(char in "0123456789abcdef" for char in value)


def _normalize_allowed_domains(domains: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(_normalize_domain(domain) for domain in domains if domain.strip()))


def _normalize_domain(domain: str) -> str:
    normalized = domain.strip().rstrip(".").lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return normalized


def _normalize_hostname(hostname: str) -> str:
    normalized = hostname.strip().rstrip(".").lower()
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return normalized


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
