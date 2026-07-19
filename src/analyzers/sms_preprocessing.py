"""Stable preprocessing functions referenced by the serialized SMS model."""

from __future__ import annotations

import re


_URL_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|\b[\w-]+\.(?:com|co\.kr|kr|net|org|ly)(?:/\S*)?)",
    re.IGNORECASE,
)


def sms_preprocessor(text: str) -> str:
    """Lowercase text and replace URLs with a stable placeholder token."""
    return _URL_PATTERN.sub(" url ", str(text).lower())
