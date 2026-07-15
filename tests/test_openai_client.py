import json
import unittest
from types import SimpleNamespace

from src.services.openai_client import (
    OpenAISecurityChatClient,
    build_analysis_snapshot,
)


class FakeResponses:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOpenAI:
    def __init__(self, response) -> None:
        self.responses = FakeResponses(response)


def make_response():
    annotation = SimpleNamespace(
        type="url_citation",
        url="https://www.kisa.or.kr/security-guide",
        title="KISA 보안 안내",
    )
    content = SimpleNamespace(
        type="output_text",
        text="공식 채널에서 발신자를 확인하세요.",
        annotations=[annotation],
    )
    return SimpleNamespace(
        id="resp_test",
        output_text="공식 채널에서 발신자를 확인하세요.",
        output=[
            SimpleNamespace(type="web_search_call"),
            SimpleNamespace(type="file_search_call"),
            SimpleNamespace(type="message", content=[content]),
        ],
    )


class AnalysisSnapshotTest(unittest.TestCase):
    def test_keeps_analysis_but_drops_unapproved_raw_fields(self) -> None:
        snapshot = build_analysis_snapshot(
            {
                "request_id": "analysis-test",
                "overall_risk": {"level": "high", "score": 0.91},
                "summary": "높은 주의가 필요합니다.",
                "risk_reasons": ["로그인 유도"],
                "recommended_actions": ["공식 채널 확인"],
                "message_analysis": {"label": "phishing"},
                "url_analysis": [{"url": "https://suspicious.example"}],
                "raw_body": "분석 단계 밖으로 보내면 안 되는 원문",
            }
        )

        self.assertEqual(snapshot["request_id"], "analysis-test")
        self.assertEqual(snapshot["overall_risk"]["level"], "high")
        self.assertNotIn("raw_body", snapshot)


class OpenAISecurityChatClientTest(unittest.TestCase):
    def test_sends_frozen_analysis_and_chat_as_separate_messages(self) -> None:
        fake = FakeOpenAI(make_response())
        client = OpenAISecurityChatClient(
            client=fake,
            model="gpt-5.6",
            vector_store_id="vs_test",
        )
        result = client.ask(
            question="이제 무엇을 해야 해?",
            analysis_result={
                "request_id": "analysis-test",
                "overall_risk": {"level": "high", "score": 0.91},
                "summary": "높은 주의가 필요합니다.",
            },
            history=[
                {"role": "user", "content": "첫 질문"},
                {"role": "assistant", "content": "첫 답변"},
            ],
        )

        call = fake.responses.calls[0]
        self.assertFalse(call["store"])
        self.assertEqual(call["model"], "gpt-5.6")
        self.assertEqual(call["input"][-1]["content"], "이제 무엇을 해야 해?")
        self.assertIn("분석 결과 스냅샷", call["input"][0]["content"])
        self.assertEqual(json.loads(call["input"][0]["content"].split("\n", 1)[1])["request_id"], "analysis-test")
        self.assertEqual(
            [tool["type"] for tool in call["tools"]],
            ["web_search", "file_search"],
        )
        self.assertEqual(result["text"], "공식 채널에서 발신자를 확인하세요.")
        self.assertEqual(result["tools_used"], ["web_search", "file_search"])
        self.assertEqual(result["citations"][0]["url"], "https://www.kisa.or.kr/security-guide")

    def test_omits_file_search_without_vector_store(self) -> None:
        fake = FakeOpenAI(make_response())
        client = OpenAISecurityChatClient(
            client=fake,
            model="gpt-5.6",
            vector_store_id=" ",
        )

        client.ask(
            question="최신 사례를 찾아줘",
            analysis_result={"overall_risk": {"level": "medium"}},
            history=[],
        )

        self.assertEqual(fake.responses.calls[0]["tools"], [{"type": "web_search"}])

    def test_rejects_blank_question_before_api_call(self) -> None:
        fake = FakeOpenAI(make_response())
        client = OpenAISecurityChatClient(client=fake, model="gpt-5.6")

        with self.assertRaises(ValueError):
            client.ask(
                question="  ",
                analysis_result={"overall_risk": {"level": "low"}},
                history=[],
            )

        self.assertEqual(fake.responses.calls, [])


if __name__ == "__main__":
    unittest.main()
