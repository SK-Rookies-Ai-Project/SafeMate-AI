import unittest
from email.message import EmailMessage

from src.analyzers.file_parser import EmlValidationError, parse_eml, validate_eml


def build_email_bytes(*, html: bool = False) -> bytes:
    message = EmailMessage()
    message["From"] = "recruit@example.com"
    message["To"] = "user@example.com"
    message["Subject"] = "채용 결과 안내"
    message.set_content("결과를 확인하세요: https://safe.example/result")
    if html:
        message.add_alternative(
            '<html><body><a href="https://link.example/login">확인</a>'
            '<img src="https://pixel.example/track.png"></body></html>',
            subtype="html",
        )
    return message.as_bytes()


class EmlParserTest(unittest.TestCase):
    def test_parses_valid_email(self) -> None:
        result = parse_eml(build_email_bytes(), "message.eml")

        self.assertEqual(result["input_type"], "email")
        self.assertEqual(result["subject"], "채용 결과 안내")
        self.assertIn("[URL]", result["body"])
        self.assertEqual(result["url_candidates"][0]["source_type"], "text")

    def test_accepts_uppercase_extension(self) -> None:
        message, _ = validate_eml("message.EML", build_email_bytes())
        self.assertEqual(message["Subject"], "채용 결과 안내")

    def test_rejects_wrong_extension(self) -> None:
        with self.assertRaises(EmlValidationError):
            validate_eml("message.txt", build_email_bytes())

    def test_rejects_suspicious_double_extension(self) -> None:
        with self.assertRaises(EmlValidationError):
            validate_eml("invoice.pdf.eml", build_email_bytes())

    def test_rejects_empty_file(self) -> None:
        with self.assertRaises(EmlValidationError):
            validate_eml("message.eml", b"")

    def test_rejects_pdf_renamed_to_eml(self) -> None:
        with self.assertRaises(EmlValidationError):
            validate_eml("message.eml", b"%PDF-1.7 fake")

    def test_rejects_plain_text_without_headers(self) -> None:
        with self.assertRaises(EmlValidationError):
            validate_eml("message.eml", b"just ordinary text")

    def test_extracts_html_href_and_image_src_without_fetching(self) -> None:
        result = parse_eml(build_email_bytes(html=True), "message.eml")
        by_type = {item["source_type"]: item["url"] for item in result["url_candidates"]}

        self.assertEqual(by_type["href"], "https://link.example/login")
        self.assertEqual(by_type["image_src"], "https://pixel.example/track.png")


if __name__ == "__main__":
    unittest.main()
