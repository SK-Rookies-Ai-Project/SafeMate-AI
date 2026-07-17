import json
import os
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


SUCCESS_RESULT = {
    "status": "success",
    "input_type": "sms",
    "overall_risk": {"level": "low", "score": 0.1},
    "summary": "로컬 분석 완료",
    "risk_reasons": [],
    "recommended_actions": ["공식 채널에서 확인하세요."],
    "message_analysis": {
        "status": "success",
        "label": "normal",
        "phishing_probability": 0.1,
        "signals": [],
        "top_features": [],
        "model_version": "test-v1",
    },
    "url_analysis": [],
    "url_analysis_summary": {},
    "web_evidence": [],
    "file_evidence": [],
    "limitations": [],
    "errors": [],
}


class _AnalysisClient:
    def __init__(self, result=SUCCESS_RESULT):
        self.result = result

    def analyze(self, request):
        return self.result


def _render_chat_caption_case():
    from src.ui.components import render_chat_response

    render_chat_response(
        {
            "content": "공식 채널로 확인",
            "action_plan": {
                "do_now": [{"id": "check", "text": "공식 채널로 확인"}]
            },
            "citations": [
                {
                    "type": "url",
                    "title": "untrusted",
                    "url": "https://example.com",
                }
            ],
            "tools_used": ["web_search", "file_search"],
            "tool_status": {"web": "failed", "file": "completed"},
            "citation_status": "accepted",
            "degraded": True,
            "fallback": "tool_failed",
        }
    )
def _render_data_notice():
    from src.ui.components import render_data_notice

    render_data_notice()


def _render_absent_tool_status_sources():
    from src.ui.components import render_chat_response

    render_chat_response(
        {
            "citations": [{"type": "url", "title": "KISA", "url": "https://www.boho.or.kr/"}],
            "tools_used": ["web_search"],
            "citation_status": "accepted",
        }
    )


def _render_not_called_tool_status_sources():
    from src.ui.components import render_chat_response

    render_chat_response(
        {
            "citations": [{"type": "url", "title": "KISA", "url": "https://www.boho.or.kr/"}],
            "tools_used": ["web_search"],
            "tool_status": {"web": "not_called"},
            "citation_status": "accepted",
        }
    )
def _render_rejected_citation_sources():
    from src.ui.components import render_chat_response

    render_chat_response(
        {
            "citations": [{"type": "url", "title": "KISA", "url": "https://www.boho.or.kr/"}],
            "tool_status": {"web": "completed"},
            "citation_status": "rejected",
        }
    )
def _render_not_called_citation_sources():
    from src.ui.components import render_chat_response

    render_chat_response(
        {
            "citations": [{"type": "url", "title": "KISA", "url": "https://www.boho.or.kr/"}],
            "tool_status": {"web": "completed"},
            "citation_status": "not_called",
        }
    )



def _render_absent_citation_status_sources():
    from src.ui.components import render_chat_response

    render_chat_response(
        {
            "citations": [{"type": "url", "title": "KISA", "url": "https://www.boho.or.kr/"}],
            "tool_status": {"web": "completed"},
        }
    )


def _render_accepted_citation_sources():
    from src.ui.components import render_chat_response

    render_chat_response(
        {
            "supplemental_claims": [
                {"text": "공식 공지", "source_scope": "web", "claim_ordinal": 0}
            ],
            "citations": [
                {
                    "type": "url",
                    "title": "KISA",
                    "url": "https://www.boho.or.kr/",
                    "claim_ordinal": 0,
                }
            ],
            "tool_status": {"web": "completed"},
            "citation_status": "accepted",
        }
    )


def _render_mismatched_tool_status_sources():
    from src.ui.components import render_chat_response

    render_chat_response(
        {
            "citations": [{"type": "file", "title": "안내문.pdf"}],
            "tools_used": ["file_search"],
            "tool_status": {"web": "completed", "file": "failed"},
            "citation_status": "accepted",
        }
    )



def _render_accepted_claim_sources():
    from src.ui.components import render_chat_response

    render_chat_response(
        {
            "supplemental_claims": [
                {"text": "웹 근거", "source_scope": "web", "claim_ordinal": 0},
                {"text": "문서 근거", "source_scope": "file", "claim_ordinal": 1},
                {"text": "복합 근거", "source_scope": "mixed", "claim_ordinal": 2},
            ],
            "citations": [
                {
                    "type": "url",
                    "title": "KISA",
                    "url": "https://www.boho.or.kr/",
                    "claim_ordinal": 0,
                },
                {"type": "file", "title": "안내문.pdf", "claim_ordinal": 1},
                {
                    "type": "url",
                    "title": "KISA 복합",
                    "url": "https://www.boho.or.kr/",
                    "claim_ordinal": 2,
                },
                {"type": "file", "title": "복합 안내문.pdf", "claim_ordinal": 2},
            ],
            "tool_status": {"web": "completed", "file": "completed"},
            "citation_status": "accepted",
        }
    )

def _run_successful_app(*, followup_enabled=False, analysis_result=SUCCESS_RESULT, chat_client=None):
    environment = {
        "SAFEMATE_OPENAI_FOLLOWUP_ENABLED": "on" if followup_enabled else "",
        "OPENAI_API_KEY": "test-key" if followup_enabled else "",
        "OPENAI_MODEL": "test-model" if followup_enabled else "",
        "OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH": (
            "tests/fixtures/provider-contract.json" if followup_enabled else ""
        ),
        "OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256": (
            "a" * 64 if followup_enabled else ""
        ),
    }
    patches = [
        patch("src.client_factory.get_analysis_client", return_value=_AnalysisClient(analysis_result)),
        patch.dict(os.environ, environment),
    ]
    if chat_client is not None:
        patches.append(patch("src.services.openai_client.OpenAISecurityChatClient", return_value=chat_client))
    with patches[0], patches[1]:
        if len(patches) == 3:
            with patches[2]:
                app = AppTest.from_file("app.py").run(timeout=10)
                app.text_area[0].set_value("의심스러운 문자입니다.").run(timeout=10)
                app.button[0].click().run(timeout=10)
                return app
        app = AppTest.from_file("app.py").run(timeout=10)
        app.text_area[0].set_value("의심스러운 문자입니다.").run(timeout=10)
        app.button[0].click().run(timeout=10)
        return app


class AppChatUiTest(unittest.TestCase):
    def test_default_off_keeps_deterministic_local_analysis_available(self) -> None:
        with patch("src.services.openai_client.OpenAISecurityChatClient") as constructor:
            app = _run_successful_app()

        constructor.assert_not_called()
        self.assertEqual(len(app.chat_input), 0)
        self.assertIn("분석 결과", [item.value for item in app.subheader])
        self.assertTrue(any("후속 대화 기능은 현재 비활성화" in item.value for item in app.info))
        self.assertEqual(len(app.exception), 0)
    def test_privacy_notice_names_prior_chat_history(self) -> None:
        app = AppTest.from_function(_render_data_notice).run(timeout=10)

        self.assertIn("이전 대화 기록", app.info[0].value)
        self.assertEqual(len(app.exception), 0)

    def test_missing_or_unknown_analysis_status_displays_error_and_never_unlocks_chat(self) -> None:
        for status in (None, "partial", "error", "pending", "unrecognized"):
            result = {**SUCCESS_RESULT}
            if status is not None:
                result["status"] = status
            else:
                result.pop("status")
            app = _run_successful_app(followup_enabled=True, analysis_result=result)

            self.assertEqual(app.session_state["analysis_status"], "error")
            self.assertIsNone(app.session_state["analysis_result"])
            self.assertIsNone(app.session_state["last_analyzed_digest"])
            self.assertEqual(len(app.chat_input), 0)
            self.assertNotIn("분석 결과", [item.value for item in app.subheader])
            self.assertTrue(
                any("분석 결과가 완료 상태인지 확인할 수 없습니다." in item.value for item in app.error)
            )
            self.assertEqual(len(app.exception), 0)

    def test_history_projection_is_closed_for_nested_unknown_and_secret_fields(self) -> None:
        from src.ui.components import build_chat_history_message

        message = build_chat_history_message(
            {
                "text": "기본 안내",
                "api_key": "top-secret",
                "action_plan": {
                    "do_now": [{"id": "check", "text": "공식 채널로 확인", "raw_token": "secret"}],
                    "unknown": {"api_key": "secret"},
                },
                "supplemental_claims": [{"text": "공식 공지", "source_scope": "web", "file_refs": [], "raw_token": "secret"}],
                "citations": [
                    {"type": "url", "title": "KISA", "url": "https://www.boho.or.kr/", "claim_ordinal": 0, "api_key": "secret"},
                    {"type": "file", "title": "안내문.pdf", "claim_ordinal": 0, "raw_token": "secret"},
                ],
                "tools_used": ["web_search", "unknown_tool"],
                "tool_status": {"web": "completed", "file": "failed", "unknown": "completed", "raw_token": "secret"},
                "unrelated": "secret",
            }
        )

        self.assertEqual(set(message), {"role", "content", "action_plan", "supplemental_claims", "citations", "tools_used", "tool_status"})
        persisted = json.dumps(message, ensure_ascii=False)
        for forbidden in ("secret", "api_key", "raw_token", "unknown", "unknown_tool"):
            self.assertNotIn(forbidden, persisted)
        self.assertEqual(message["action_plan"], {"do_now": [{"id": "check", "text": "공식 채널로 확인"}]})
        self.assertEqual(
            message["citations"][0]["claim_ordinal"],
            0,
        )

    def test_failed_chat_turn_cannot_mutate_committed_history(self) -> None:
        class ChatClient:
            def __init__(self):
                self.histories = []

            def ask(self, *, question, analysis_result, history):
                self.histories.append(history)
                if len(self.histories) == 2:
                    history[1]["action_plan"]["do_now"][0]["text"] = "변조됨"
                    raise RuntimeError("transient failure")
                return {
                    "text": "첫 답변",
                    "action_plan": {"do_now": [{"id": "check", "text": "공식 채널로 확인"}]},
                }

        chat_client = ChatClient()
        with (
            patch("src.client_factory.get_analysis_client", return_value=_AnalysisClient()),
            patch.dict(
                os.environ,
                {
                    "SAFEMATE_OPENAI_FOLLOWUP_ENABLED": "on",
                    "OPENAI_API_KEY": "test-key",
                    "OPENAI_MODEL": "test-model",
                    "OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH": (
                        "tests/fixtures/provider-contract.json"
                    ),
                    "OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256": "a" * 64,
                },
                clear=True,
            ),
            patch(
                "src.services.openai_client.OpenAISecurityChatClient",
                return_value=chat_client,
            ),
        ):
            app = AppTest.from_file("app.py").run(timeout=10)
            app.text_area[0].set_value("의심스러운 문자입니다.").run(timeout=10)
            app.button[0].click().run(timeout=10)
            app.chat_input[0].set_value("첫 질문").run(timeout=10)
            app.chat_input[0].set_value("실패 질문").run(timeout=10)

        self.assertEqual(len(chat_client.histories), 2)
        self.assertEqual(
            [message["role"] for message in app.session_state["chat_messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(app.session_state["chat_messages"][0]["content"], "첫 질문")
        self.assertEqual(
            app.session_state["chat_messages"][1]["action_plan"]["do_now"][0]["text"],
            "공식 채널로 확인",
        )

    def test_outbound_history_has_no_arbitrary_assistant_secrets(self) -> None:
        class ChatClient:
            def __init__(self):
                self.histories = []

            def ask(self, *, question, analysis_result, history):
                self.histories.append(history)
                return {
                    "text": "답변",
                    "action_plan": {"do_now": [{"id": "check", "text": "확인", "api_key": "secret"}]},
                    "raw_token": "secret",
                }

        chat_client = ChatClient()
        with (
            patch("src.client_factory.get_analysis_client", return_value=_AnalysisClient()),
            patch.dict(
                os.environ,
                {
                    "SAFEMATE_OPENAI_FOLLOWUP_ENABLED": "on",
                    "OPENAI_API_KEY": "test-key",
                    "OPENAI_MODEL": "test-model",
                    "OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH": (
                        "tests/fixtures/provider-contract.json"
                    ),
                    "OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256": "a" * 64,
                },
                clear=True,
            ),
            patch(
                "src.services.openai_client.OpenAISecurityChatClient",
                return_value=chat_client,
            ),
        ):
            app = AppTest.from_file("app.py").run(timeout=10)
            app.text_area[0].set_value("의심스러운 문자입니다.").run(timeout=10)
            app.button[0].click().run(timeout=10)
            app.chat_input[0].set_value("첫 질문").run(timeout=10)
            app.chat_input[0].set_value("둘째 질문").run(timeout=10)

        self.assertNotIn("secret", json.dumps(chat_client.histories[1], ensure_ascii=False))
        self.assertEqual(chat_client.histories[1][0]["role"], "user")
        self.assertEqual(
            chat_client.histories[1][1]["action_plan"],
            {"do_now": [{"id": "check", "text": "확인"}]},
        )
    def test_claims_require_matching_citations_and_completed_scope_tools(self) -> None:
        from src.ui.components import _renderable_supplemental_claims

        claims = [
            {"text": "웹 근거", "source_scope": "web", "claim_ordinal": 0},
            {"text": "문서 근거", "source_scope": "file", "claim_ordinal": 1},
            {"text": "복합 근거", "source_scope": "mixed", "claim_ordinal": 2},
        ]
        citations = [
            {"type": "url", "title": "웹", "url": "https://www.boho.or.kr/", "claim_ordinal": 0},
            {"type": "file", "title": "문서", "claim_ordinal": 1},
            {"type": "url", "title": "복합 웹", "url": "https://www.boho.or.kr/", "claim_ordinal": 2},
            {"type": "file", "title": "복합 문서", "claim_ordinal": 2},
        ]
        self.assertEqual(
            _renderable_supplemental_claims(
                claims,
                citations,
                {"web": "completed", "file": "completed"},
                "accepted",
            ),
            claims,
        )
        negative_cases = (
            (claims, citations, "rejected", {"web": "completed", "file": "completed"}),
            (claims, citations, None, {"web": "completed", "file": "completed"}),
            (
                [claims[0]],
                [],
                "accepted",
                {"web": "completed", "file": "completed"},
            ),
            (
                [claims[0]],
                [{"type": "file", "title": "문서", "claim_ordinal": 0}],
                "accepted",
                {"web": "completed", "file": "completed"},
            ),
            (
                [claims[0]],
                [{"type": "url", "title": "다른 주장", "url": "https://www.boho.or.kr/", "claim_ordinal": 99}],
                "accepted",
                {"web": "completed", "file": "completed"},
            ),
            (
                [claims[2]],
                [{"type": "url", "title": "복합 웹", "url": "https://www.boho.or.kr/", "claim_ordinal": 2}],
                "accepted",
                {"web": "completed", "file": "completed"},
            ),
            (
                [claims[0]],
                [{"type": "url", "title": "웹", "url": "https://www.boho.or.kr/", "claim_ordinal": 0}],
                "accepted",
                {"web": "failed", "file": "completed"},
            ),
        )
        for case_claims, case_citations, citation_status, tool_status in negative_cases:
            with self.subTest(
                claims=case_claims,
                citations=case_citations,
                citation_status=citation_status,
                tool_status=tool_status,
            ):
                self.assertEqual(
                    _renderable_supplemental_claims(
                        case_claims,
                        case_citations,
                        tool_status,
                        citation_status,
                    ),
                    [],
                )

    def test_sources_are_limited_to_admitted_claim_ordinals(self) -> None:
        from src.ui.components import render_chat_sources

        self.assertIsNone(
            render_chat_sources(
                [
                    {
                        "type": "url",
                        "title": "다른 주장",
                        "url": "https://www.boho.or.kr/",
                        "claim_ordinal": 9,
                    }
                ],
                {"web": "completed"},
                "accepted",
                allowed_claim_ordinals={0},
            )
        )
    def test_accepted_web_file_and_mixed_claims_render_compact_sources(self) -> None:
        app = AppTest.from_function(_render_accepted_claim_sources).run(timeout=10)

        self.assertEqual(len(app.get("expander")), 1)
        self.assertEqual(
            {item.value for item in app.text},
            {
                "• 웹 근거",
                "• 문서 근거",
                "• 복합 근거",
                "KISA",
                "안내문.pdf",
                "KISA 복합",
                "복합 안내문.pdf",
            },
        )
        self.assertIn("출처: 웹 검색 · 보안 문서 검색", [item.value for item in app.caption])
        self.assertEqual(len(app.exception), 0)
    def test_noncompleted_tools_hide_sources(self) -> None:
        for renderer in (
            _render_absent_tool_status_sources,
            _render_not_called_tool_status_sources,
            _render_mismatched_tool_status_sources,
        ):
            app = AppTest.from_function(renderer).run(timeout=10)
            captions = [item.value for item in app.caption]

            self.assertEqual(len(app.get("expander")), 0)
            self.assertIn(
                "후속 안내에 확인되어 표시할 수 있는 출처가 없습니다.", captions
            )
            self.assertEqual(len(app.exception), 0)

    def test_rejected_not_called_or_absent_citation_status_hides_completed_tool_sources(self) -> None:
        for renderer in (
            _render_rejected_citation_sources,
            _render_not_called_citation_sources,
            _render_absent_citation_status_sources,
        ):
            app = AppTest.from_function(renderer).run(timeout=10)

            self.assertEqual(len(app.get("expander")), 0)
            self.assertEqual(len(app.exception), 0)

    def test_accepted_citation_has_one_source_container_and_provenance_line(self) -> None:
        app = AppTest.from_function(_render_accepted_citation_sources).run(timeout=10)
        captions = [item.value for item in app.caption]

        self.assertEqual(len(app.get("expander")), 1)
        self.assertEqual(captions.count("출처: 웹 검색"), 1)
        self.assertFalse(any(value.startswith("완료한 도구:") for value in captions))
        self.assertEqual([item.value for item in app.text].count("KISA"), 1)
        self.assertEqual(len(app.exception), 0)

    def test_chat_captions_require_renderable_sources_and_completed_tool_state(self) -> None:
        app = AppTest.from_function(_render_chat_caption_case).run(timeout=10)
        captions = [item.value for item in app.caption]
        self.assertEqual([item.value for item in app.text].count("지금 할 일"), 1)
        self.assertEqual(
            [item.value for item in app.text].count("• 공식 채널로 확인"), 1
        )
        self.assertNotIn(
            "공식 채널로 확인",
            [item.value for item in app.text if item.value != "• 공식 채널로 확인"],
        )
        self.assertIn("후속 안내에 확인되어 표시할 수 있는 출처가 없습니다.", captions)
        self.assertEqual(captions.count("추가 확인이 제한되어 기본 대응 안내만 제공합니다."), 1)
        self.assertEqual(len(app.get("expander")), 0)


if __name__ == "__main__":
    unittest.main()
