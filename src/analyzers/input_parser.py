"""Normalize direct SMS input and extract URL candidates safely."""

from __future__ import annotations

import hashlib
import re
from typing import Literal, TypedDict

from src.config import MAX_SMS_CHARS


class InputValidationError(ValueError):
    """Raised when user-provided text cannot be analyzed."""


class UrlCandidate(TypedDict):
    url: str
    source_type: Literal["text", "href", "image_src"]
    input_index: int


URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"']+")
TRAILING_URL_PUNCTUATION = ".,!?;:)]}>"


def _clean_url(raw_url: str) -> str:
    return raw_url.rstrip(TRAILING_URL_PUNCTUATION)


def extract_text_url_candidates(
    text: str,
    *,
    source_type: Literal["text", "href", "image_src"] = "text",
    start_index: int = 0,
) -> list[UrlCandidate]:
    """Return URL candidates in first-appearance order without fetching them."""
    candidates: list[UrlCandidate] = []
    for match in URL_PATTERN.finditer(text):
        url = _clean_url(match.group(0))
        if not url:
            continue
        candidates.append(
            {
                "url": url,
                "source_type": source_type,
                "input_index": start_index + len(candidates),
            }
        )
    return candidates


def replace_text_urls(text: str, replacement: str = "[URL]") -> str:
    """Replace detected text URLs while preserving trailing punctuation."""

    def replace_match(match: re.Match[str]) -> str:
        raw_url = match.group(0)
        clean_url = _clean_url(raw_url)
        trailing = raw_url[len(clean_url) :]
        return replacement + trailing

    return URL_PATTERN.sub(replace_match, text)


def prepare_sms_input(raw_text: str) -> dict:
    """Validate and normalize SMS text into the common input shape."""
    normalized_text = raw_text.strip()
    if not normalized_text:
        raise InputValidationError("분석할 문자 내용을 입력해 주세요.")
    if len(normalized_text) > MAX_SMS_CHARS:
        raise InputValidationError("문자 내용이 최대 입력 길이를 초과했습니다.")

    candidates = extract_text_url_candidates(normalized_text)
    return {
        "input_type": "sms",
        "preview": {
            "body": normalized_text,
            "url_candidates": candidates,
        },
        "subject": None,
        "body": replace_text_urls(normalized_text),
        "url_candidates": candidates,
    }


def create_input_digest(input_type: str, content: bytes) -> str:
    """Create a stable digest that includes both input type and content."""
    return hashlib.sha256(input_type.encode("utf-8") + b":" + content).hexdigest()
