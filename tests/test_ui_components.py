import unittest

from src.ui.components import _format_file_location, _safe_http_url


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


if __name__ == "__main__":
    unittest.main()
