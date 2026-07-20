"""Unified SMS and email model entry point."""

from typing import Literal

from src.analyzers.email_model import analyze_email
from src.analyzers.sms_model import analyze_sms


ROUTER_VERSION = "message-router-v1"


def analyze_message(
    text: str,
    input_type: Literal["sms", "email"],
    subject: str | None = None,
) -> dict:
    """Route normalized message text to the matching local classifier."""
    if not isinstance(text, str) or not text.strip():
        return _routing_error("INVALID_TEXT", "분석할 메시지 본문이 없습니다.")
    if input_type == "email":
        return analyze_email(text.strip(), subject=subject)
    if input_type == "sms":
        return analyze_sms(text.strip())
    return _routing_error("INVALID_INPUT_TYPE", "지원하지 않는 메시지 유형입니다.")


def _routing_error(code: str, message: str) -> dict:
    return {
        "status": "error",
        "label": "unknown",
        "phishing_probability": None,
        "signals": [],
        "top_features": [],
        "model_version": ROUTER_VERSION,
        "error": {
            "code": code,
            "message": message,
            "retryable": False,
        },
    }
