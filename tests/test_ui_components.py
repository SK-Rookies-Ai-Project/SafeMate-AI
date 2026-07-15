import unittest

from src.ui.components import (
    _format_file_location,
    _safe_http_url,
    build_chat_suggestions,
)


class UiComponentsTest(unittest.TestCase):
    def test_allows_only_http_and_https_source_links(self) -> None:
        self.assertEqual(
            _safe_http_url("https://www.kisa.or.kr/notice"),
            "https://www.kisa.or.kr/notice",
        )
        self.assertEqual(
            _safe_http_url("http://example.go.kr/guide"),
            "http://example.go.kr/guide",
        )
        self.assertIsNone(_safe_http_url("javascript:alert(1)"))
        self.assertIsNone(_safe_http_url("file:///tmp/guide.pdf"))

    def test_formats_file_search_location(self) -> None:
        self.assertEqual(
            _format_file_location({"filename": "smishing_guide.pdf", "page": 12}),
            "smishing_guide.pdf · 12쪽",
        )

    def test_builds_high_risk_url_chat_suggestions(self) -> None:
        suggestions = build_chat_suggestions(
            {
                "input_type": "sms",
                "overall_risk": {"level": "high"},
                "url_analysis": [{"url": "https://suspicious.example"}],
            }
        )

        self.assertEqual(suggestions[0], "지금 가장 먼저 해야 할 일은 무엇인가요?")
        self.assertIn("이미 링크를 눌렀다면 어떻게 해야 하나요?", suggestions)
        self.assertIn("이 URL에서 어떤 위험 신호가 발견됐나요?", suggestions)
        self.assertEqual(len(suggestions), 4)

    def test_prioritizes_href_mismatch_suggestion(self) -> None:
        suggestions = build_chat_suggestions(
            {
                "input_type": "email",
                "overall_risk": {"level": "medium"},
                "url_analysis": [{"display_href_mismatch": True}],
            }
        )

        self.assertIn("표시 주소와 실제 연결 주소가 왜 다른가요?", suggestions)

    def test_builds_low_risk_verification_suggestions(self) -> None:
        suggestions = build_chat_suggestions(
            {
                "input_type": "sms",
                "overall_risk": {"level": "low"},
                "url_analysis": [],
            }
        )

        self.assertEqual(suggestions[0], "추가로 확인해야 할 위험 요소가 있나요?")
        self.assertIn("이 문자가 정상인지 확인하는 방법을 알려주세요.", suggestions)


if __name__ == "__main__":
    unittest.main()
