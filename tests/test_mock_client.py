import unittest

from src.analyzers.input_parser import prepare_sms_input
from src.ui.mock_client import MockAnalysisClient, build_analysis_request


class MockAnalysisClientTest(unittest.TestCase):
    def test_returns_analysis_response_shape(self) -> None:
        prepared = prepare_sms_input("긴급 확인: https://example.com")
        request = build_analysis_request(prepared, "analysis-test")

        result = MockAnalysisClient().analyze(request)

        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["request_id"], "analysis-test")
        self.assertEqual(result["input_type"], "sms")
        self.assertEqual(result["overall_risk"]["level"], "high")
        self.assertEqual(result["url_analysis_summary"]["analyzed_count"], 1)
        self.assertEqual(result["url_analysis"][0]["status"], "success")

    def test_builds_json_compatible_request(self) -> None:
        prepared = prepare_sms_input("안내 메시지")
        request = build_analysis_request(prepared, "analysis-test")

        self.assertEqual(
            set(request),
            {
                "schema_version",
                "request_id",
                "input_type",
                "subject",
                "body",
                "url_candidates",
            },
        )

    def test_deduplicates_and_prioritizes_url_candidates(self) -> None:
        request = {
            "schema_version": "1.0",
            "request_id": "analysis-priority",
            "input_type": "email",
            "subject": "테스트",
            "body": "URL 후보 테스트",
            "url_candidates": [
                {"url": "https://image.example", "source_type": "image_src", "input_index": 0},
                {"url": "https://href.example", "source_type": "href", "input_index": 1},
                {"url": "https://text.example", "source_type": "text", "input_index": 2},
                {"url": "https://text.example", "source_type": "href", "input_index": 3},
            ],
        }

        result = MockAnalysisClient().analyze(request)

        self.assertEqual(result["url_analysis_summary"]["candidate_count"], 3)
        self.assertEqual(
            [item["url"] for item in result["url_analysis"]],
            [
                "https://text.example",
                "https://href.example",
                "https://image.example",
            ],
        )
        duplicate = result["url_analysis"][0]
        self.assertEqual(duplicate["input_indexes"], [2, 3])
        self.assertEqual(duplicate["occurrence_count"], 2)
        self.assertEqual(duplicate["source_types"], ["text", "href"])

    def test_preserves_html_link_mismatch_signal(self) -> None:
        request = {
            "schema_version": "1.0",
            "request_id": "analysis-html-mismatch",
            "input_type": "email",
            "subject": "계정 확인",
            "body": "링크를 확인하세요.",
            "url_candidates": [
                {
                    "url": "https://evil.example/login",
                    "source_type": "href",
                    "input_index": 0,
                    "displayed_url": "https://official.example/login",
                    "displayed_domain": "official.example",
                    "destination_domain": "evil.example",
                    "display_href_mismatch": True,
                    "signals": ["표시 주소와 실제 연결 도메인이 다릅니다."],
                }
            ],
        }

        result = MockAnalysisClient().analyze(request)

        self.assertIn(
            "표시 주소와 실제 연결 도메인이 다릅니다.",
            result["url_analysis"][0]["signals"],
        )
        self.assertTrue(result["url_analysis"][0]["display_href_mismatch"])
        self.assertIn(
            "이메일에 표시된 주소와 실제 연결 주소가 다릅니다.",
            result["risk_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
