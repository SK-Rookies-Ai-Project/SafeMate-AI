from typing import Literal

from email_model import analyze_email
from sms_model import analyze_sms


def analyze_message(
    text: str,
    input_type: Literal["sms", "email"],
    subject: str | None = None,
) -> dict:

    # 입력값 검증
    if not text or not text.strip():
        return {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": [],
            "top_features": [],
            "model_version": "message-v1",
            "error": "empty_text",
        }

    # SMS 모델 호출
    if input_type == "sms":
        return analyze_sms(text)

    # 이메일 모델 호출
    if input_type == "email":
        return analyze_email(
            text=text,
            subject=subject,
        )

    # 지원하지 않는 입력 유형 처리
    return {
        "status": "error",
        "label": "unknown",
        "phishing_probability": None,
        "signals": [],
        "top_features": [],
        "model_version": "message-v1",
        "error": "invalid_input_type",
    }