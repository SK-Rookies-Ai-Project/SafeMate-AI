"""Validate and parse untrusted RFC-style .eml uploads without fetching URLs."""

from __future__ import annotations

from email import policy
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from src.analyzers.input_parser import (
    UrlCandidate,
    extract_text_url_candidates,
    replace_text_urls,
)
from src.config import (
    KNOWN_BINARY_SIGNATURES,
    MAX_EML_SIZE_BYTES,
    SUSPICIOUS_PREVIOUS_EXTENSIONS,
)

RECOGNIZED_EMAIL_HEADERS = ("From", "To", "Subject", "Date", "Message-ID")


class EmlValidationError(ValueError):
    """Raised when an uploaded file is not a supported email message."""


class _SafeHtmlExtractor(HTMLParser):
    """Extract visible text and URL attributes without rendering or fetching."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.attribute_urls: list[tuple[str, Literal["href", "image_src"]]] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text_parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.lower() == "a" and attributes.get("href"):
            self.attribute_urls.append((attributes["href"] or "", "href"))
        if tag.lower() == "img" and attributes.get("src"):
            self.attribute_urls.append((attributes["src"] or "", "image_src"))


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


def _parse_html(html: str) -> _SafeHtmlExtractor:
    parser = _SafeHtmlExtractor()
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
    candidates = extract_text_url_candidates(body)
    _, html_parts = _message_text_parts(message)
    for html in html_parts:
        parser = _parse_html(html)
        for raw_url, source_type in parser.attribute_urls:
            if raw_url.lower().startswith(("cid:", "data:")):
                continue
            attribute_candidates = extract_text_url_candidates(
                raw_url,
                source_type=source_type,
                start_index=len(candidates),
            )
            candidates.extend(attribute_candidates)
    return candidates


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
