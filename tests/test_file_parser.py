import unittest
from email.message import EmailMessage

from src.analyzers.file_parser import EmlValidationError, parse_eml, validate_eml
from src.config import MAX_URL_CANDIDATES


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


def build_html_email(html: str) -> bytes:
    message = EmailMessage()
    message["From"] = "recruit@example.com"
    message["To"] = "user@example.com"
    message["Subject"] = "링크 확인"
    message.set_content("HTML 이메일을 확인하세요.")
    message.add_alternative(html, subtype="html")
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

    def test_flags_visible_url_and_href_domain_mismatch(self) -> None:
        result = parse_eml(
            build_html_email(
                '<a href="https://evil.example/login">https://official.example/login</a>'
            ),
            "message.eml",
        )
        href = next(
            item for item in result["url_candidates"] if item["source_type"] == "href"
        )

        self.assertEqual(href["displayed_url"], "https://official.example/login")
        self.assertEqual(href["displayed_domain"], "official.example")
        self.assertEqual(href["destination_domain"], "evil.example")
        self.assertTrue(href["display_href_mismatch"])
        self.assertIn("표시 주소와 실제 연결 도메인이 다릅니다.", href["signals"])

    def test_does_not_flag_related_subdomain_as_mismatch(self) -> None:
        result = parse_eml(
            build_html_email(
                '<a href="https://accounts.example.com/login">https://www.example.com</a>'
            ),
            "message.eml",
        )
        href = next(
            item for item in result["url_candidates"] if item["source_type"] == "href"
        )

        self.assertFalse(href["display_href_mismatch"])
        self.assertEqual(href["signals"], [])

    def test_decodes_html_entities_in_href(self) -> None:
        result = parse_eml(
            build_html_email(
                '<a href="https://example.com/check?a=1&amp;b=2">확인</a>'
            ),
            "message.eml",
        )
        href = next(
            item for item in result["url_candidates"] if item["source_type"] == "href"
        )

        self.assertEqual(href["url"], "https://example.com/check?a=1&b=2")

    def test_ignores_non_web_href_schemes(self) -> None:
        result = parse_eml(
            build_html_email(
                '<a href="javascript:alert(1)">실행</a>'
                '<a href="mailto:security@example.com">메일</a>'
                '<a href="data:text/plain,test">데이터</a>'
            ),
            "message.eml",
        )

        self.assertFalse(
            any(item["source_type"] == "href" for item in result["url_candidates"])
        )

    def test_caps_html_url_candidates_before_request_building(self) -> None:
        anchors = "".join(
            f'<a href="https://example.com/{index}">링크 {index}</a>'
            for index in range(MAX_URL_CANDIDATES + 50)
        )

        result = parse_eml(build_html_email(anchors), "message.eml")

        self.assertEqual(len(result["url_candidates"]), MAX_URL_CANDIDATES)
        self.assertEqual(
            result["url_candidates"][-1]["input_index"],
            MAX_URL_CANDIDATES - 1,
        )


if __name__ == "__main__":
    unittest.main()
