from typing import Literal

from email_model import analyze_email
from sms_model import analyze_sms


def analyze_message(
    text: str,
    input_type: Literal["sms", "email"],
    subject: str | None = None,
) -> dict:

    try:

        if not text or not text.strip():
            return {
                "status": "error",
                "label": "unknown",
                "phishing_probability": None,
                "signals": [],
                "top_features": [],
                "model_version": "message-v1",
                "error": "empty text"
            }

        if input_type == "email":

            return analyze_email(
                text=text,
                subject=subject
            )

        elif input_type == "sms":

            return analyze_sms(
                text=text
            )

        return {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": [],
            "top_features": [],
            "model_version": "message-v1",
            "error": "invalid input_type"
        }

    except Exception:

        return {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": [],
            "top_features": [],
            "model_version": "message-v1",
            "error": "analysis failed"
        }