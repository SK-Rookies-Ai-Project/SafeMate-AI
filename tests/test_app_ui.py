import unittest

from streamlit.testing.v1 import AppTest


class AppChatUiTest(unittest.TestCase):
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
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
