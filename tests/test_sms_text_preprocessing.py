from src.analyzers.sms_preprocessing import sms_preprocessor


def test_sms_preprocessor_lowercases_and_replaces_urls() -> None:
    result = sms_preprocessor("긴급 HTTPS://Bit.LY/AbC 지금 확인")

    assert result == "긴급  url  지금 확인"


def test_sms_preprocessor_preserves_non_url_text() -> None:
    assert sms_preprocessor("일반 안내 문자") == "일반 안내 문자"
