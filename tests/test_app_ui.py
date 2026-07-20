import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def _local_agent_result(request: dict) -> dict:
    from src.client_factory import get_analysis_client

    return {
        "analysis_result": get_analysis_client().analyze(request),
        "supplemental_text": None,
        "tools_used": [],
        "citations": [],
        "fallback_used": True,
    }


def _successful_agent_result(request: dict) -> dict:
    result = _local_agent_result(request)
    result.update(
        {
            "supplemental_text": "KISA 안내에 따르면 공식 채널 확인이 필요합니다.",
            "tools_used": ["web_search", "file_search"],
            "citations": [
                {
                    "type": "url",
                    "title": "KISA 보안 안내",
                    "url": "https://www.kisa.or.kr/guide",
                    "start_index": 0,
                    "end_index": 12,
                },
                {"type": "file", "title": "스미싱 대응 지침.pdf"},
            ],
            "fallback_used": False,
        }
    )
    return result
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


def _render_chat_sources() -> None:
    from src.ui.components import render_chat_sources

    render_chat_sources(
        citations=[
            {
                "type": "url",
                "title": "KISA 보안 안내",
                "url": "https://www.kisa.or.kr/guide",
            },
            {
                "type": "url",
                "title": "검증되지 않은 링크",
                "url": "https://unreviewed.example/guide",
            },
            {"type": "file", "title": "스미싱 대응 지침.pdf"},
        ],
        tools_used=["web_search", "file_search", "unknown_tool"],
    )


def _render_cited_response() -> None:
    from src.ui.components import render_cited_response

    render_cited_response(
        "공식 채널에서 확인하세요.",
        citations=[
            {
                "type": "url",
                "title": "KISA 보안 안내",
                "url": "https://www.kisa.or.kr/guide",
                "start_index": 0,
                "end_index": 6,
            },
            {"type": "file", "title": "스미싱 대응 지침.pdf"},
        ],
        tools_used=["web_search", "file_search"],
    )


def _render_untrusted_cited_response() -> None:
    from src.ui.components import render_cited_response

    text = (
        "공식 안내 [악성 링크](https://evil.example/path) "
        "<https://evil.example/auto> https://evil.example/bare"
    )
    render_cited_response(
        text,
        citations=[
            {
                "type": "url",
                "title": "KISA 보안 안내",
                "url": "https://www.kisa.or.kr/guide",
                "start_index": 0,
                "end_index": 5,
            }
        ],
        tools_used=["web_search"],
    )


def _render_injected_official_citation_url() -> None:
    from src.ui.components import render_cited_response

    render_cited_response(
        "공식 안내",
        citations=[
            {
                "type": "url",
                "title": "조작된 공식 출처 URL",
                "url": (
                    "https://www.kisa.or.kr/) "
                    "[EVIL](https://evil.example"
                ),
                "start_index": 0,
                "end_index": 5,
            }
        ],
        tools_used=["web_search"],
    )


class AppChatUiTest(unittest.TestCase):
    def test_session_state_omits_unused_analysis_digest(self) -> None:
        app = AppTest.from_file("app.py").run(timeout=10)

        self.assertNotIn("last_analyzed_digest", app.session_state)

    def test_analysis_button_stays_visibly_enabled_without_input(self) -> None:
        app = AppTest.from_file("app.py").run(timeout=10)

        self.assertFalse(app.button[0].disabled)
        app.button[0].click().run(timeout=10)

        self.assertEqual(app.warning[0].value, "분석할 문자 내용을 입력해 주세요.")
        self.assertEqual(len(app.exception), 0)
    def test_shows_clickable_suggestions_only_after_analysis(self) -> None:
        app = AppTest.from_file("app.py").run(timeout=10)
        self.assertEqual(len(app.chat_input), 0)

        with patch(
            "src.services.openai_client.SafeMateAgent.analyze",
            side_effect=_local_agent_result,
        ):
            app.text_area[0].set_value(
                "[긴급 안내] 계정 인증이 필요합니다. "
                "https://suspicious.example/login"
            ).run(timeout=10)
            app.button[0].click().run(timeout=10)

        labels = [button.label for button in app.button]
        self.assertTrue(
            {
                "추가로 확인해야 할 위험 요소가 있나요?",
                "왜 주의가 필요한지 쉽게 설명해 주세요.",
                "지금 가장 먼저 해야 할 일은 무엇인가요?",
            }
            & set(labels)
        )
        self.assertIn("이 문자가 정상인지 확인하는 방법을 알려주세요.", labels)
        self.assertIn("이 URL에서 어떤 위험 신호가 발견됐나요?", labels)
        self.assertEqual(
            app.chat_input[0].placeholder,
            "분석 결과에 대해 궁금한 점을 직접 입력하세요.",
        )
        self.assertGreaterEqual(len(app.get("image")), 2)
        self.assertNotIn("문자를 분석하지 못했습니다.", [item.value for item in app.error])
        self.assertEqual(len(app.exception), 0)

        app.text_area[0].set_value("완전히 다른 문자 내용").run(timeout=10)

        self.assertEqual(len(app.chat_input), 0)
        self.assertNotIn("분석 결과", [item.value for item in app.subheader])

    def test_analysis_stores_and_renders_supplement_separately(self) -> None:
        app = AppTest.from_file("app.py").run(timeout=10)

        with patch(
            "src.services.openai_client.SafeMateAgent.analyze",
            side_effect=_successful_agent_result,
        ) as analyze:
            app.text_area[0].set_value(
                "계정 확인 안내 https://suspicious.example/login"
            ).run(timeout=10)
            app.button[0].click().run(timeout=10)

        analyze.assert_called_once()
        self.assertIsNotNone(app.session_state["analysis_result"])
        self.assertEqual(
            app.session_state["supplemental_analysis"]["text"],
            "KISA 안내에 따르면 공식 채널 확인이 필요합니다.",
        )
        self.assertIn("AI 추가 조사", [item.value for item in app.subheader])
        self.assertIn(
            "사용한 도구: 웹 검색 · 보안 문서 검색",
            [item.value for item in app.caption],
        )
        self.assertEqual(len(app.exception), 0)

        app.text_area[0].set_value("새로운 입력").run(timeout=10)
        self.assertIsNone(app.session_state["supplemental_analysis"])
        self.assertNotIn("AI 추가 조사", [item.value for item in app.subheader])

    def test_rejects_agent_analysis_without_explicit_status(self) -> None:
        invalid_agent_result = _local_agent_result(
            {
                "schema_version": "1.0",
                "request_id": "analysis-invalid-status",
                "input_type": "sms",
                "body": "test",
                "url_candidates": [],
            }
        )
        invalid_agent_result["analysis_result"].pop("status", None)
        app = AppTest.from_file("app.py").run(timeout=10)

        with patch(
            "src.services.openai_client.SafeMateAgent.analyze",
            return_value=invalid_agent_result,
        ):
            app.text_area[0].set_value("상태 계약 테스트").run(timeout=10)
            app.button[0].click().run(timeout=10)

        self.assertIsNone(app.session_state["analysis_result"])
        self.assertIsNone(app.session_state["supplemental_analysis"])
        self.assertEqual(app.session_state["analysis_status"], "error")
        self.assertIn(
            "분석 중 오류가 발생했습니다. 입력을 유지한 채 다시 시도해 주세요.",
            [item.value for item in app.error],
        )

        with patch(
            "src.services.openai_client.SafeMateAgent.analyze",
            side_effect=_successful_agent_result,
        ):
            app.button[0].click().run(timeout=10)
        self.assertIsNotNone(app.session_state["supplemental_analysis"])

        app.button[1].click().run(timeout=10)
        self.assertIsNone(app.session_state["supplemental_analysis"])
        self.assertNotIn("AI 추가 조사", [item.value for item in app.subheader])

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

    def test_chat_sources_show_known_tools_and_only_safe_links(self) -> None:
        app = AppTest.from_function(_render_chat_sources).run(timeout=10)

        self.assertEqual(
            app.caption[0].value,
            "사용한 도구: 웹 검색 · 보안 문서 검색",
        )
        self.assertEqual(
            [item.value for item in app.text],
            ["[1] KISA 보안 안내", "[2] 스미싱 대응 지침.pdf"],
        )
        self.assertEqual(len(app.get("link_button")), 1)
        self.assertEqual(
            app.get("link_button")[0].url,
            "https://www.kisa.or.kr/guide",
        )
        self.assertEqual(len(app.exception), 0)

    def test_cited_response_inserts_clickable_number_near_claim(self) -> None:
        app = AppTest.from_function(_render_cited_response).run(timeout=10)

        markdown_values = [item.value for item in app.markdown]
        self.assertTrue(
            any(
                "[1](https://www.kisa.or.kr/guide)" in value
                for value in markdown_values
            )
        )
        self.assertEqual(
            [button.label for button in app.get("link_button")],
            ["[1] 공식 출처 열기"],
        )
        self.assertIn("[2] 스미싱 대응 지침.pdf", [item.value for item in app.text])
        self.assertEqual(len(app.exception), 0)

    def test_cited_response_escapes_model_authored_links(self) -> None:
        app = AppTest.from_function(_render_untrusted_cited_response).run(timeout=10)

        rendered = "\n".join(item.value for item in app.markdown)
        self.assertIn("[1](https://www.kisa.or.kr/guide)", rendered)
        self.assertNotIn("](https://evil.example/path)", rendered)
        self.assertNotIn("<https://evil.example/auto>", rendered)
        self.assertNotIn("https://evil.example/bare", rendered)
        self.assertEqual(
            [button.url for button in app.get("link_button")],
            ["https://www.kisa.or.kr/guide"],
        )
        self.assertEqual(len(app.exception), 0)

    def test_cited_response_encodes_markdown_delimiters_in_official_url(self) -> None:
        app = AppTest.from_function(_render_injected_official_citation_url).run(
            timeout=10
        )

        rendered = "\n".join(item.value for item in app.markdown)
        self.assertIn(
            "[1](https://www.kisa.or.kr/%29%20%5BEVIL%5D%28https"
            "://evil.example)",
            rendered,
        )
        self.assertNotIn("] [EVIL](https://evil.example", rendered)
        self.assertEqual(rendered.count("]("), 1)
        self.assertEqual(len(app.exception), 0)

if __name__ == "__main__":
    unittest.main()
