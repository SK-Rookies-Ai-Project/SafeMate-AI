import unittest

from streamlit.testing.v1 import AppTest
def _render_message_failure() -> None:
    from src.ui.components import _render_message_analysis

    _render_message_analysis(
        {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": ["should not display"],
            "top_features": [{"name": "should not chart"}],
            "model_version": "sms-model-v1",
            "error": {
                "code": "MODEL_NOT_AVAILABLE",
                "message": "메시지 분석 모델을 사용할 수 없습니다.",
                "retryable": False,
            },
        }
    )


def _render_pending_message() -> None:
    from src.ui.components import _render_message_analysis

    _render_message_analysis({"status": "pending"})


def _render_message_success() -> None:
    from src.ui.components import _render_message_analysis

    _render_message_analysis(
        {
            "status": "success",
            "label": "phishing",
            "phishing_probability": 0.65,
            "signals": [],
            "top_features": [],
            "model_version": "email-v1",
        },
        input_type="email",
    )


def _render_empty_evidence() -> None:
    from src.ui.components import _render_evidence

    _render_evidence({"web_evidence": [], "file_evidence": []})



class AppChatUiTest(unittest.TestCase):
    def test_analysis_button_stays_visibly_enabled_without_input(self) -> None:
        app = AppTest.from_file("app.py").run(timeout=10)

        self.assertFalse(app.button[0].disabled)
        app.button[0].click().run(timeout=10)

        self.assertEqual(app.warning[0].value, "분석할 문자 내용을 입력해 주세요.")
        self.assertEqual(len(app.exception), 0)
    def test_shows_clickable_suggestions_only_after_analysis(self) -> None:
        app = AppTest.from_file("app.py").run(timeout=10)
        self.assertEqual(len(app.chat_input), 0)

        app.text_area[0].set_value(
            "[긴급 안내] 계정 인증이 필요합니다. "
            "https://suspicious.example/login"
        ).run(timeout=10)
        app.button[0].click().run(timeout=10)

        labels = [button.label for button in app.button]
        self.assertIn("추가로 확인해야 할 위험 요소가 있나요?", labels)
        self.assertIn("이 문자가 정상인지 확인하는 방법을 알려주세요.", labels)
        self.assertIn("이 URL에서 어떤 위험 신호가 발견됐나요?", labels)
        self.assertEqual(
            app.chat_input[0].placeholder,
            "분석 결과에 대해 궁금한 점을 직접 입력하세요.",
        )
        self.assertEqual(len(app.get("image")), 2)
        self.assertIn("문자를 분석하지 못했습니다.", [item.value for item in app.error])
        self.assertEqual(len(app.exception), 0)

    def test_renders_message_model_failure_without_success_charts(self) -> None:
        app = AppTest.from_function(_render_message_failure).run(timeout=10)

        self.assertEqual(app.error[0].value, "메시지 분석 모델을 사용할 수 없습니다.")
        self.assertEqual(
            [element.value for element in app.text],
            ["분류: unknown", "모델 버전: sms-model-v1"],
        )
        self.assertEqual(len(app.get("image")), 0)
        self.assertEqual(len(app.exception), 0)

    def test_renders_unexpected_message_status_as_unavailable(self) -> None:
        app = AppTest.from_function(_render_pending_message).run(timeout=10)

        self.assertEqual(
            app.info[0].value, "메시지 분석 결과를 현재 표시할 수 없습니다."
        )
        self.assertEqual(len(app.get("image")), 0)
        self.assertEqual(len(app.exception), 0)

    def test_labels_combined_spam_scam_result_honestly(self) -> None:
        app = AppTest.from_function(_render_message_success).run(timeout=10)

        text_values = [element.value for element in app.text]
        self.assertIn("분류: 스팸·사기 의심", text_values)
        self.assertIn("스팸·사기 통합 점수: 65%", text_values)
        self.assertIn(
            "광고성 스팸, 사기, 피싱을 포함한 통합 분류 결과이며 "
            "피싱만의 확률을 의미하지 않습니다.",
            [element.value for element in app.caption],
        )
        self.assertEqual(len(app.get("image")), 1)
        self.assertEqual(len(app.exception), 0)

    def test_empty_evidence_shows_honest_official_resources(self) -> None:
        app = AppTest.from_function(_render_empty_evidence).run(timeout=10)

        self.assertIn("직접 인용된 공식 출처는 없습니다", app.info[0].value)
        self.assertEqual(len(app.get("link_button")), 2)
        self.assertEqual(len(app.exception), 0)

if __name__ == "__main__":
    unittest.main()
