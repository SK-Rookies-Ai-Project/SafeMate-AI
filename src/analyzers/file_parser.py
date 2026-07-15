"""Validate and parse untrusted RFC-style .eml uploads without fetching URLs."""

from __future__ import annotations

from email import policy
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from src.analyzers.input_parser import (
    UrlCandidate,
    extract_text_url_candidates,
    replace_text_urls,
)
from src.config import (
    KNOWN_BINARY_SIGNATURES,
    MAX_EML_SIZE_BYTES,
    MAX_URL_CANDIDATES,
    SUSPICIOUS_PREVIOUS_EXTENSIONS,
)

RECOGNIZED_EMAIL_HEADERS = ("From", "To", "Subject", "Date", "Message-ID")


class EmlValidationError(ValueError):
    """Raised when an uploaded file is not a supported email message."""


class _SafeHtmlExtractor(HTMLParser):
    """Extract visible text and URL attributes without rendering or fetching."""

    def __init__(self, *, max_attribute_urls: int = MAX_URL_CANDIDATES) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.attribute_urls: list[dict] = []
        self._active_anchor: dict | None = None
        self._max_attribute_urls = max(0, max_attribute_urls)

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text_parts.append(data.strip())
        if self._active_anchor is not None:
            self._active_anchor["visible_text"] += data

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.lower() == "a" and attributes.get("href"):
            if len(self.attribute_urls) >= self._max_attribute_urls:
                self._active_anchor = None
                return
            anchor = {
                "url": (attributes["href"] or "").strip(),
                "source_type": "href",
                "visible_text": "",
            }
            self.attribute_urls.append(anchor)
            self._active_anchor = anchor
        if tag.lower() == "img" and attributes.get("src"):
            if len(self.attribute_urls) >= self._max_attribute_urls:
                return
            self.attribute_urls.append(
                {
                    "url": (attributes["src"] or "").strip(),
                    "source_type": "image_src",
                    "visible_text": "",
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            self._active_anchor = None


def _content_as_text(part: Message) -> str:
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except (LookupError, UnicodeDecodeError):
        pass

    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _message_text_parts(message: Message) -> tuple[list[str], list[str]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            plain_parts.append(_content_as_text(part))
        elif content_type == "text/html":
            html_parts.append(_content_as_text(part))
    return plain_parts, html_parts


def _parse_html(
    html: str,
    *,
    max_attribute_urls: int = MAX_URL_CANDIDATES,
) -> _SafeHtmlExtractor:
    parser = _SafeHtmlExtractor(max_attribute_urls=max_attribute_urls)
    parser.feed(html)
    parser.close()
    return parser


def extract_text_body(message: Message) -> str:
    """Prefer plain text, falling back to visible HTML text only."""
    plain_parts, html_parts = _message_text_parts(message)
    plain_text = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    if plain_text:
        return plain_text

    visible_parts: list[str] = []
    for html in html_parts:
        visible_parts.extend(_parse_html(html).text_parts)
    return "\n".join(visible_parts).strip()


def extract_url_candidates(message: Message, body: str) -> list[UrlCandidate]:
    """Collect visible text, href, and image-src URL candidates in order."""
    candidates = extract_text_url_candidates(body, max_candidates=MAX_URL_CANDIDATES)
    if len(candidates) >= MAX_URL_CANDIDATES:
        return candidates
    _, html_parts = _message_text_parts(message)
    for html in html_parts:
        remaining = MAX_URL_CANDIDATES - len(candidates)
        if remaining <= 0:
            break
        parser = _parse_html(html, max_attribute_urls=remaining)
        for attribute in parser.attribute_urls:
            raw_url = attribute["url"]
            source_type = attribute["source_type"]
            if raw_url.lower().startswith(("cid:", "data:")):
                continue
            attribute_candidates = extract_text_url_candidates(
                raw_url,
                source_type=source_type,
                start_index=len(candidates),
                max_candidates=MAX_URL_CANDIDATES - len(candidates),
            )
            if source_type == "href":
                metadata = _build_href_metadata(
                    raw_url,
                    attribute.get("visible_text", ""),
                )
                for candidate in attribute_candidates:
                    candidate.update(metadata)
            candidates.extend(attribute_candidates)
            if len(candidates) >= MAX_URL_CANDIDATES:
                break
    return candidates


def _build_href_metadata(href: str, visible_text: str) -> dict:
    displayed_candidates = extract_text_url_candidates(
        visible_text,
        max_candidates=1,
    )
    if not displayed_candidates:
        compact_text = "".join(visible_text.split())
        if compact_text != visible_text:
            displayed_candidates = extract_text_url_candidates(
                compact_text,
                max_candidates=1,
            )
    if not displayed_candidates:
        return {"display_href_mismatch": False, "signals": []}

    displayed_url = displayed_candidates[0]["url"]
    displayed_domain = _normalized_hostname(displayed_url)
    destination_domain = _normalized_hostname(href)
    mismatch = bool(
        displayed_domain
        and destination_domain
        and not _domains_are_related(displayed_domain, destination_domain)
    )
    return {
        "displayed_url": displayed_url,
        "displayed_domain": displayed_domain,
        "destination_domain": destination_domain,
        "display_href_mismatch": mismatch,
        "signals": (
            ["표시 주소와 실제 연결 도메인이 다릅니다."] if mismatch else []
        ),
    }


def _normalized_hostname(url: str) -> str | None:
    candidate = url.strip()
    if candidate.lower().startswith("www."):
        candidate = "https://" + candidate
    try:
        hostname = urlsplit(candidate).hostname
    except ValueError:
        return None
    if not hostname:
        return None
    normalized = hostname.rstrip(".").lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return normalized


def _domains_are_related(first: str, second: str) -> bool:
    return (
        first == second
        or first.endswith("." + second)
        or second.endswith("." + first)
    )


def validate_eml(filename: str, file_bytes: bytes) -> tuple[Message, list[str]]:
    """Validate extension, size, obvious signatures, and email structure."""
    extensions = [suffix.lower() for suffix in Path(filename).suffixes]
    if not extensions or extensions[-1] != ".eml":
        raise EmlValidationError(".eml 파일만 업로드할 수 있습니다.")
    if len(extensions) >= 2 and extensions[-2] in SUSPICIOUS_PREVIOUS_EXTENSIONS:
        raise EmlValidationError("이중 확장자가 의심되는 파일입니다.")
    if not file_bytes:
        raise EmlValidationError("파일 내용이 비어 있습니다.")
    if len(file_bytes) > MAX_EML_SIZE_BYTES:
        raise EmlValidationError("파일 크기는 25MB 이하여야 합니다.")

    sample = file_bytes[:4096].lstrip()
    for signature, detected_type in KNOWN_BINARY_SIGNATURES:
        if sample.startswith(signature):
            raise EmlValidationError(
                f"확장자는 .eml이지만 실제 내용은 {detected_type} 파일로 추정됩니다."
            )

    try:
        message = BytesParser(policy=policy.default).parsebytes(file_bytes)
    except Exception as exc:
        raise EmlValidationError("이메일 형식을 파싱할 수 없습니다.") from exc

    if not any(message.get(header) for header in RECOGNIZED_EMAIL_HEADERS):
        raise EmlValidationError("유효한 이메일 헤더를 찾을 수 없습니다.")

    body = extract_text_body(message).strip()
    subject = str(message.get("Subject", "")).strip()
    if not subject and not body:
        raise EmlValidationError("이메일 제목과 본문을 찾을 수 없습니다.")

    warnings = [
        type(defect).__name__
        for part in message.walk()
        for defect in part.defects
    ]
    return message, warnings


def parse_eml(file_bytes: bytes, filename: str) -> dict:
    """Parse a validated email into the common analysis input shape."""
    message, parse_warnings = validate_eml(filename, file_bytes)
    original_body = extract_text_body(message)
    subject = str(message.get("Subject", "")).strip()
    candidates = extract_url_candidates(message, original_body)

    return {
        "input_type": "email",
        "preview": {
            "from": str(message.get("From", "")),
            "to": str(message.get("To", "")),
            "subject": subject,
            "body": original_body,
            "url_candidates": candidates,
        },
        "subject": subject or None,
        "body": replace_text_urls(original_body),
        "url_candidates": candidates,
        "parse_warnings": parse_warnings,
    }
