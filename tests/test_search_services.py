import unittest
from types import SimpleNamespace

from src.services.file_search import (
    FILE_SEARCH_INCLUDE,
    build_file_search_tool,
    is_file_search_call,
    normalize_file_citation,
)
from src.services.web_search import (
    WEB_SEARCH_INCLUDE,
    build_web_search_tool,
    is_web_search_call,
    normalize_web_citation,
)


class WebSearchServiceTest(unittest.TestCase):
    def test_builds_hosted_web_search_tool(self) -> None:
        self.assertEqual(build_web_search_tool(), {"type": "web_search"})
        self.assertEqual(WEB_SEARCH_INCLUDE, "web_search_call.action.sources")

    def test_identifies_web_search_call(self) -> None:
        self.assertTrue(is_web_search_call({"type": "web_search_call"}))
        self.assertFalse(is_web_search_call({"type": "message"}))

    def test_normalizes_web_citation(self) -> None:
        citation = normalize_web_citation(
            SimpleNamespace(
                type="url_citation",
                title="공식 보안 안내",
                url="https://security.example/guide",
            )
        )

        self.assertEqual(
            citation,
            {
                "type": "url",
                "title": "공식 보안 안내",
                "url": "https://security.example/guide",
            },
        )
        self.assertIsNone(normalize_web_citation({"type": "file_citation"}))


class FileSearchServiceTest(unittest.TestCase):
    def test_builds_hosted_file_search_tool(self) -> None:
        self.assertEqual(
            build_file_search_tool("vs_test"),
            {
                "type": "file_search",
                "vector_store_ids": ["vs_test"],
                "max_num_results": 5,
            },
        )
        self.assertEqual(FILE_SEARCH_INCLUDE, "file_search_call.results")

    def test_rejects_blank_vector_store_id(self) -> None:
        with self.assertRaises(ValueError):
            build_file_search_tool("  ")

    def test_identifies_file_search_call(self) -> None:
        self.assertTrue(is_file_search_call({"type": "file_search_call"}))
        self.assertFalse(is_file_search_call({"type": "message"}))

    def test_normalizes_file_citation(self) -> None:
        citation = normalize_file_citation(
            SimpleNamespace(
                type="file_citation",
                filename="smishing_guide.pdf",
                file_id="file_test",
            )
        )

        self.assertEqual(
            citation,
            {
                "type": "file",
                "title": "smishing_guide.pdf",
                "file_id": "file_test",
            },
        )
        self.assertIsNone(normalize_file_citation({"type": "url_citation"}))


if __name__ == "__main__":
    unittest.main()
