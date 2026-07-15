import unittest

from src.analyzers.input_parser import (
    InputValidationError,
    create_input_digest,
    prepare_sms_input,
    replace_text_urls,
)
from src.config import MAX_SMS_CHARS


class SmsInputParserTest(unittest.TestCase):
    def test_prepares_sms_and_preserves_url_candidate(self) -> None:
        result = prepare_sms_input("결과 확인: https://example.com/path.")

        self.assertEqual(result["input_type"], "sms")
        self.assertEqual(result["subject"], None)
        self.assertEqual(result["body"], "결과 확인: [URL].")
        self.assertEqual(result["url_candidates"][0]["url"], "https://example.com/path")
        self.assertEqual(result["url_candidates"][0]["input_index"], 0)

    def test_rejects_blank_sms(self) -> None:
        with self.assertRaises(InputValidationError):
            prepare_sms_input("   \n")

    def test_rejects_sms_over_limit(self) -> None:
        with self.assertRaises(InputValidationError):
            prepare_sms_input("가" * (MAX_SMS_CHARS + 1))

    def test_replaces_multiple_urls(self) -> None:
        text = "https://one.example/a 와 www.two.example/b!"
        self.assertEqual(replace_text_urls(text), "[URL] 와 [URL]!")

    def test_digest_changes_by_input_type(self) -> None:
        content = "same".encode()
        self.assertNotEqual(
            create_input_digest("sms", content),
            create_input_digest("email", content),
        )


if __name__ == "__main__":
    unittest.main()
