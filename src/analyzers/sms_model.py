"""SMS phishing model entry point."""

from pathlib import Path

from src.analyzers.message_model_common import analyze_with_model


MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "sms_spam_model.pkl"
MODEL_VERSION = "sms-v1"


def analyze_sms(text: str) -> dict:
    """Analyze SMS text without loading the model during module import."""
    return analyze_with_model(
        text,
        model_path=MODEL_PATH,
        model_version=MODEL_VERSION,
        unavailable_message="문자 분석 모델을 사용할 수 없습니다.",
        failure_message="문자를 분석하지 못했습니다.",
    )
