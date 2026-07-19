import json
import unittest
from unittest.mock import patch

from src.analyzers.email_model import analyze_email
from src.analyzers.sms_model import analyze_sms
from src.analyzers.text_analyzer import analyze_message


class FakeBinaryModel:
    classes_ = [0, 1]

    def __init__(self, phishing_probability: float) -> None:
        self.phishing_probability = phishing_probability
        self.inputs: list[list[str]] = []

    def predict_proba(self, values: list[str]) -> list[list[float]]:
        self.inputs.append(values)
        return [[1.0 - self.phishing_probability, self.phishing_probability]]


class MessageAnalyzerTest(unittest.TestCase):
    def test_routes_email_with_subject(self) -> None:
        with patch(
            "src.analyzers.text_analyzer.analyze_email",
            return_value={"status": "success"},
        ) as analyzer:
            result = analyze_message("본문", "email", subject="제목")

        self.assertEqual(result, {"status": "success"})
        analyzer.assert_called_once_with("본문", subject="제목")

    def test_routes_sms_without_subject(self) -> None:
        with patch(
            "src.analyzers.text_analyzer.analyze_sms",
            return_value={"status": "success"},
        ) as analyzer:
            result = analyze_message("문자 본문", "sms")

        self.assertEqual(result, {"status": "success"})
        analyzer.assert_called_once_with("문자 본문")

    def test_rejects_blank_text_and_unknown_input_type(self) -> None:
        blank = analyze_message("  ", "sms")
        unknown = analyze_message("본문", "chat")  # type: ignore[arg-type]

        self.assertEqual(blank["error"]["code"], "INVALID_TEXT")
        self.assertEqual(unknown["error"]["code"], "INVALID_INPUT_TYPE")
        self.assertEqual(blank["label"], "unknown")
        self.assertIsNone(blank["phishing_probability"])

    def test_email_model_uses_subject_and_returns_contract(self) -> None:
        model = FakeBinaryModel(0.84)
        with patch(
            "src.analyzers.message_model_common._load_model",
            return_value=model,
        ):
            result = analyze_email("비밀번호를 입력하세요.", subject="긴급 계정 확인")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["label"], "phishing")
        self.assertEqual(result["phishing_probability"], 0.84)
        self.assertIn("긴급성을 강조하는 표현", result["signals"])
        self.assertIn("개인정보 또는 인증정보 입력 요구", result["signals"])
        self.assertEqual(model.inputs, [["긴급 계정 확인 비밀번호를 입력하세요."]])
        self.assertIsNone(result["error"])

    def test_sms_model_returns_safe_missing_model_error(self) -> None:
        with patch(
            "src.analyzers.message_model_common._load_model",
            side_effect=FileNotFoundError,
        ):
            result = analyze_sms("일반 문자")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["label"], "unknown")
        self.assertEqual(result["error"]["code"], "MODEL_NOT_AVAILABLE")
        self.assertNotIn("sms_spam_model.pkl", result["error"]["message"])

    def test_sms_model_uses_optimized_threshold(self) -> None:
        below_threshold = FakeBinaryModel(0.95)
        above_threshold = FakeBinaryModel(0.97)

        with patch(
            "src.analyzers.message_model_common._load_model",
            side_effect=[below_threshold, above_threshold],
        ):
            normal = analyze_sms("확인 링크를 눌러주세요")
            phishing = analyze_sms("확인 링크를 눌러주세요")

        self.assertEqual(normal["label"], "normal")
        self.assertEqual(normal["signals"], [])
        self.assertEqual(phishing["label"], "phishing")
        self.assertIn("URL 또는 외부 접속 유도 표현", phishing["signals"])

    def test_results_are_strict_json_serializable(self) -> None:
        result = analyze_message("", "email")
        serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)

        self.assertIn("INVALID_TEXT", serialized)


if __name__ == "__main__":
    unittest.main()
