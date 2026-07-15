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


if __name__ == "__main__":
    unittest.main()
