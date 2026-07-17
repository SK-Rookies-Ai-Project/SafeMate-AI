import json
import unittest
from unittest.mock import patch

from src.services.followup_telemetry import (
    MAX_DURATION_MS,
    FollowupTelemetry,
    SCHEMA_VERSION,
    host_turn_reference,
    validate_event,
)
from src.services.openai_client import OpenAISecurityChatClient
from src.services.security_action import FUNCTION_NAME


class Responses:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Client:
    def __init__(self, *items):
        self.responses = Responses(*items)


def function_call():
    return {
        "type": "function_call", "status": "completed", "name": FUNCTION_NAME,
        "call_id": "provider-call-id", "arguments": json.dumps({
            "user_goal": "general", "observed_event": "unknown", "event_explicitly_reported": False,
        }),
    }


def action_response(*output):
    return {"status": "completed", "output": list(output)}


def message_output(text):
    return {
        "type": "message",
        "status": "completed",
        "content": [{"type": "output_text", "text": text}],
    }


def supplemental_response():
    text = json.dumps({"schema_version": "safemate.supplemental.v2", "claims": []})
    return {
        "status": "completed",
        "output": [message_output(text)],
        "output_text": text,
    }


class FollowupTelemetryTest(unittest.TestCase):
    def _event(self):
        events = []
        telemetry = FollowupTelemetry(events.append, seed=b"a" * 32)
        telemetry.emit(phase="phase_one", state="started", tool="function", model="gpt-test")
        return events[0]

    def test_exact_closed_schema_and_framed_reference(self):
        event = self._event()
        self.assertEqual(event["schema_version"], SCHEMA_VERSION)
        self.assertEqual(set(event), {
            "schema_version", "host_turn_ref", "phase", "attempt", "tool", "state", "reason",
            "duration_ms", "model_alias", "token_count", "tool_count", "result_count", "claim_count",
            "fallback", "vector_state", "corpus_version",
        })
        self.assertEqual(event["host_turn_ref"], host_turn_reference(b"a" * 32))
        self.assertNotIn("a" * 32, json.dumps(event))
        self.assertNotEqual(event["host_turn_ref"], host_turn_reference(b"b" * 32))

    def test_validation_drops_unknown_forbidden_and_out_of_bounds_values(self):
        event = self._event()
        self.assertEqual(validate_event(event), event)
        for key, value in (
            ("provider_response_id", "resp_private"),
            ("corpus_version", "private-file.pdf"),
            ("reason", "prompt: private input"),
            ("duration_ms", MAX_DURATION_MS + 1),
            ("host_turn_ref", "call_provider"),
        ):
            candidate = dict(event)
            candidate[key] = value
            self.assertIsNone(validate_event(candidate))

    def test_sink_failure_and_provider_identifiers_do_not_change_result(self):
        responses = (action_response(function_call()), supplemental_response())
        normal = OpenAISecurityChatClient(
            client=Client(*responses), model="gpt-test", followup_enabled=True, provider_ready=True,
        ).ask(question="private question", analysis_result={"request_id": "host-private", "overall_risk": {"level": "low"}}, history=[])
        failing = OpenAISecurityChatClient(
            client=Client(*responses), model="gpt-test", followup_enabled=True, provider_ready=True,
            telemetry_sink=lambda _: (_ for _ in ()).throw(RuntimeError("sink failure")),
        ).ask(question="private question", analysis_result={"request_id": "host-private", "overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(
            {key: value for key, value in failing.items() if key != "response_scope"},
            {key: value for key, value in normal.items() if key != "response_scope"},
        )

    def test_unready_trust_preflight_makes_zero_provider_calls(self):
        events = []
        provider = Client(action_response(function_call()))
        client = OpenAISecurityChatClient(
            client=provider, model="gpt-test", followup_enabled=True,
            provider_ready=False, telemetry_sink=events.append,
        )
        result = client.ask(question="private question", analysis_result={"request_id": "host-private", "overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(result["fallback"], "provider_contract_unavailable")
        self.assertEqual(provider.responses.calls, [])
        self.assertEqual(events[-1]["phase"], "preflight")
        self.assertEqual(events[-1]["fallback"], "provider_contract_unavailable")
        self.assertNotIn("private question", json.dumps(events))
        self.assertNotIn("host-private", json.dumps(events))
    def test_major_fallbacks_emit_their_stable_reason(self):
        cases = (
            ("function_request_failed", (RuntimeError("provider"),), True),
            ("function_rejected", (action_response(),), True),
            ("provider_contract_unavailable", (action_response(function_call()),), False),
            ("hosted_request_failed", (action_response(function_call()), RuntimeError("provider")), True),
            ("response_shape_drift", (action_response(function_call()), {"status": "failed", "output": []}), True),
            ("supplemental_rejected", (action_response(function_call()), {"status": "completed", "output": [message_output("{}")], "output_text": "{}"}), True),
            ("hosted_tool_failed", (action_response(function_call()), {
                "status": "completed",
                "output": [
                    {"type": "web_search_call", "status": "failed"},
                    message_output(json.dumps({"schema_version": "safemate.supplemental.v2", "claims": []})),
                ],
                "output_text": json.dumps({"schema_version": "safemate.supplemental.v2", "claims": []}),
            }), True),
        )
        for reason, responses, ready in cases:
            with self.subTest(reason=reason):
                events = []
                result = OpenAISecurityChatClient(
                    client=Client(*responses), model="gpt-test", followup_enabled=True,
                    provider_ready=ready, telemetry_sink=events.append,
                ).ask(question="private question", analysis_result={"overall_risk": {"level": "low"}}, history=[])
                self.assertEqual(result["fallback"], reason)
                self.assertEqual(events[-1]["fallback"], reason)

    def test_phase_two_limit_emits_fallback_without_a_second_provider_call(self):
        events = []
        provider = Client(action_response(function_call()))
        client = OpenAISecurityChatClient(
            client=provider, model="gpt-test", followup_enabled=True,
            provider_ready=True, telemetry_sink=events.append,
        )
        with patch("src.services.openai_client.MAX_PHASE_TWO_INPUT_BYTES", 0):
            result = client.ask(question="private question", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(result["fallback"], "phase_two_input_limit")
        self.assertEqual(len(provider.responses.calls), 1)
        self.assertEqual(events[-1]["attempt"], 2)
        self.assertEqual(events[-1]["fallback"], "phase_two_input_limit")
    def test_citation_acceptance_and_rejection_are_observable(self):
        accepted_events = []
        accepted = OpenAISecurityChatClient(
            client=Client(action_response(function_call()), supplemental_response()), model="gpt-test",
            followup_enabled=True, provider_ready=True, telemetry_sink=accepted_events.append,
        ).ask(question="private question", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertIsNone(accepted["fallback"])
        self.assertEqual(accepted_events[-1]["state"], "accepted")
        self.assertTrue(all(validate_event(event) == event for event in accepted_events))
        self.assertEqual(
            [(event["phase"], event["attempt"]) for event in accepted_events],
            [("phase_one", 1), ("function", 1), ("phase_two", 2), ("citation", 1)],
        )

        rejected_events = []
        rejected_text = json.dumps({"schema_version": "safemate.supplemental.v2", "claims": [{
            "text": "private claim", "source_scope": "web", "file_refs": [],
        }]})
        rejected = OpenAISecurityChatClient(
            client=Client(action_response(function_call()), {
                "status": "completed",
                "output": [message_output(rejected_text)],
                "output_text": rejected_text,
            }), model="gpt-test", followup_enabled=True, provider_ready=True,
            telemetry_sink=rejected_events.append,
        ).ask(question="private question", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(rejected["fallback"], "citation_rejected")
        self.assertEqual(rejected_events[-1]["phase"], "citation")
        self.assertNotIn("private annotation", json.dumps(rejected_events))
        self.assertNotIn("private claim", json.dumps(rejected_events))




if __name__ == "__main__":
    unittest.main()
