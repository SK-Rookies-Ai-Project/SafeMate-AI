import unittest

from src.analyzers.input_parser import prepare_sms_input
from src.config import MAX_ANALYSIS_REQUEST_BYTES, MAX_URL_CANDIDATES
from src.contracts import AnalysisRequestValidationError, build_analysis_request


class AnalysisRequestTest(unittest.TestCase):
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

    def test_caps_url_candidates_in_final_request(self) -> None:
        prepared = {
            "input_type": "email",
            "subject": "URL 제한 테스트",
            "body": "본문",
            "url_candidates": [
                {
                    "url": f"https://example.com/{index}",
                    "source_type": "href",
                    "input_index": index,
                }
                for index in range(MAX_URL_CANDIDATES + 50)
            ],
        }

        request = build_analysis_request(prepared, "analysis-url-limit")

        self.assertEqual(len(request["url_candidates"]), MAX_URL_CANDIDATES)

    def test_rejects_oversized_final_request(self) -> None:
        prepared = {
            "input_type": "email",
            "subject": "요청 크기 제한 테스트",
            "body": "가" * MAX_ANALYSIS_REQUEST_BYTES,
            "url_candidates": [],
        }

        with self.assertRaises(AnalysisRequestValidationError):
            build_analysis_request(prepared, "analysis-size-limit")


if __name__ == "__main__":
    unittest.main()
