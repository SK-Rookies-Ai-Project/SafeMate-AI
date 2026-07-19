"""Email phishing model entry point."""

from pathlib import Path

from src.analyzers.message_model_common import analyze_with_model, extract_email_top_features


MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "email_spam_model.pkl"
MODEL_VERSION = "email-v1"


def analyze_email(text: str, subject: str | None = None) -> dict:
    """Analyze an email body and optional subject without loading on import."""
    full_text = f"{subject or ''} {text}".strip()
    return analyze_with_model(
        full_text,
        model_path=MODEL_PATH,
        model_version=MODEL_VERSION,
        unavailable_message="이메일 분석 모델을 사용할 수 없습니다.",
        failure_message="이메일을 분석하지 못했습니다.",
        threshold=0.5,
        top_feature_extractor=extract_email_top_features,
    )
