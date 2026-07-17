import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services.openai_client import (
    MAX_ANALYSIS_SNAPSHOT_BYTES,
    OpenAISecurityChatClient,
    _parse_supplemental,
    _valid_phase_two_output,
    _bounded_readiness,
    build_analysis_snapshot,
)
from src.services.security_action import FUNCTION_NAME


class OrderedResponses:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class VectorFiles:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.pop(0)


class FakeOpenAI:
    def __init__(self, *responses, vector_pages=None):
        self.responses = OrderedResponses(*responses)
        self.vector_files = VectorFiles(vector_pages or [])
        self.vector_stores = SimpleNamespace(files=self.vector_files)
class ScriptedClock:
    def __init__(self, *values):
        self.values = list(values)
        self.last = values[-1] if values else 0.0

    def __call__(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last


class AdvancingClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def action_response(*items):
    return {"status": "completed", "output": list(items)}


_UNSET = object()


def function_call(arguments=_UNSET, **extra):
    item = {
        "type": "function_call", "status": "completed", "name": FUNCTION_NAME,
        "call_id": "call_1",
        "arguments": json.dumps(
            {"user_goal": "general", "observed_event": "unknown", "event_explicitly_reported": False}
            if arguments is _UNSET
            else arguments
        ),
    }
    item.update(extra)
    return item

def function_call_raw(arguments: str, **extra):
    item = function_call(**extra)
    item["arguments"] = arguments
    return item

def supplemental_response(claims=None, output=None):
    payload = {"schema_version": "safemate.supplemental.v2", "claims": claims or []}
    output_text = json.dumps(payload, ensure_ascii=False)
    message = {
        "type": "message",
        "status": "completed",
        "content": [{"type": "output_text", "text": output_text}],
    }
    if output is None:
        output = [message]
    else:
        output = list(output)
        for item in output:
            if item.get("type") == "message":
                item["status"] = "completed"
                item.setdefault("content", []).append(
                    {"type": "output_text", "text": output_text}
                )
    return {"status": "completed", "output_text": output_text, "output": output}
def message_output(text, annotations=_UNSET):
    part = {"type": "output_text", "text": text}
    if annotations is not _UNSET:
        part["annotations"] = annotations
    return {"type": "message", "status": "completed", "content": [part]}



def _write_provider_artifacts(directory: str, *, model: str, sdk_version: str) -> dict[str, str]:
    root = Path(directory)
    vector = {
        "schema": "safemate.vector_inventory_attestation.v1",
        "sdk_version": sdk_version,
        "model": model,
        "vector_store_id": "vs_test",
        "corpus_version": "2026-07",
        "issued_at": "2026-07-01T00:00:00Z",
        "expires_at": "2026-07-31T00:00:00Z",
        "corpus_manifest_digest": "d" * 64,
        "completed_file_count": 1,
        "files": [{"file_id": "file_private", "filename": "guide.pdf", "sha256": "c" * 64}],
    }
    vector_content = json.dumps(vector, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    vector_path = root / "vector.json"
    vector_path.write_bytes(vector_content)
    receipt = {
        "schema": "safemate.provider_probe_receipt.v1",
        "sdk_version": sdk_version,
        "model": model,
        "probed_at": "2026-07-17T00:00:00Z",
        "ceilings": {"max_retries": 0, "responses": 4, "vector_operations": 212, "max_output_tokens": 512, "max_tool_calls": 5},
        "checks": {"function": True, "web": True, "file": True, "store": True},
        "counts": {"approved_files": 1, "completed_files": 1, "response_attempts": 4},
        "states": {"function_replay": "completed", "web_search": "completed", "file_search": "completed", "upload": "completed"},
        "vector_attestation_digest": hashlib.sha256(vector_content).hexdigest(),
        "corpus_manifest_digest": "d" * 64,
    }
    receipt_content = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    receipt_digest = hashlib.sha256(receipt_content).hexdigest()
    attestation = {
        "schema": "safemate.provider_contract_attestation.v1",
        "sdk_version": sdk_version,
        "model": model,
        "issued_at": "2026-07-01T00:00:00Z",
        "expires_at": "2026-07-31T00:00:00Z",
        "checks": receipt["checks"],
        "probe_receipt_digest": receipt_digest,
        "reviewer_id": "offline-test",
    }
    attestation_content = json.dumps(attestation, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    attestation_path = root / "provider.json"
    receipts_path = Path(f"{attestation_path}.receipts")
    receipts_path.mkdir()
    attestation_path.write_bytes(attestation_content)
    (receipts_path / f"{receipt_digest}.json").write_bytes(receipt_content)
    return {
        "OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH": str(attestation_path),
        "OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256": hashlib.sha256(attestation_content).hexdigest(),
        "OPENAI_VECTOR_INVENTORY_ATTESTATION_PATH": str(vector_path),
        "OPENAI_VECTOR_INVENTORY_ATTESTATION_SHA256": hashlib.sha256(vector_content).hexdigest(),
    }


class AnalysisSnapshotTest(unittest.TestCase):
    def test_keeps_analysis_but_drops_unapproved_raw_fields(self):
        snapshot = build_analysis_snapshot({"request_id": "analysis-test", "overall_risk": {"level": "high"}, "raw_body": "private"})
        self.assertEqual(snapshot["request_id"], "analysis-test")
        self.assertNotIn("raw_body", snapshot)
    def test_snapshot_enforces_structural_and_byte_limits(self):
        with self.assertRaises(ValueError):
            build_analysis_snapshot({"summary": "가" * MAX_ANALYSIS_SNAPSHOT_BYTES})
        nested = value = {}
        for _ in range(7):
            child = {}
            value["child"] = child
            value = child
        with self.assertRaises(ValueError):
            build_analysis_snapshot({"message_analysis": nested})
        with self.assertRaises(ValueError):
            build_analysis_snapshot({"risk_reasons": list(range(51))})


class SupplementalParserTest(unittest.TestCase):
    def test_parser_is_total_for_malformed_source_scope_and_output_requires_message(self):
        self.assertIsNone(
            _parse_supplemental(
                json.dumps(
                    {
                        "schema_version": "safemate.supplemental.v2",
                        "claims": [{"text": "x", "source_scope": [], "file_refs": []}],
                    }
                )
            )
        )
        client = OpenAISecurityChatClient(
            client=FakeOpenAI(action_response(function_call()), supplemental_response(output=[])),
            model="gpt-test",
            followup_enabled=True,
            provider_ready=True,
        )
        result = client.ask(question="도움", analysis_result={}, history=[])
        self.assertEqual(result["fallback"], "response_shape_drift")
    def test_parser_rejects_utf8_overage_and_duplicate_keys(self):
        oversized = '{"schema_version":"safemate.supplemental.v2","claims":[],"x":"' + ("가" * 6000) + '"}'
        self.assertIsNone(_parse_supplemental(oversized))
        self.assertIsNone(
            _parse_supplemental(
                '{"schema_version":"safemate.supplemental.v2","schema_version":"safemate.supplemental.v2","claims":[]}'
            )
        )
    def test_parser_rejects_lone_surrogates_without_raising(self):
        self.assertIsNone(_parse_supplemental("\ud800"))
        self.assertIsNone(
            _parse_supplemental(
                '{"schema_version":"safemate.supplemental.v2","claims":[{"text":"\\ud800","source_scope":"web","file_refs":[]}]}'
            )
        )
    def test_phase_two_message_accepts_mapping_and_sdk_annotations_but_rejects_malformed_parts(self):
        output_text = '{"schema_version":"safemate.supplemental.v2","claims":[]}'
        annotation = {
            "type": "url_citation", "url": "https://www.kisa.or.kr/", "title": "KISA",
            "start_index": 0, "end_index": 1,
        }
        mapping = message_output(output_text, [annotation])
        sdk = SimpleNamespace(
            type="message",
            status="completed",
            content=[SimpleNamespace(type="output_text", text=output_text, annotations=[annotation])],
        )
        self.assertTrue(_valid_phase_two_output([mapping], False, output_text))
        self.assertTrue(_valid_phase_two_output([sdk], False, output_text))
        self.assertFalse(_valid_phase_two_output([message_output(output_text, {})], False, output_text))
        self.assertFalse(_valid_phase_two_output([message_output(output_text, [annotation] * 33)], False, output_text))
        self.assertFalse(_valid_phase_two_output([message_output(output_text, [{"type": "unknown"}])], False, output_text))
        self.assertFalse(_valid_phase_two_output([message_output(output_text, [{**annotation, "start_index": True}])], False, output_text))
        self.assertFalse(_valid_phase_two_output([message_output(output_text, [{**annotation, "extra": "rejected"}])], False, output_text))
        self.assertTrue(_valid_phase_two_output([message_output(output_text, [{
            "type": "file_citation", "file_id": "file_private", "filename": "guide.pdf", "index": 0,
        }])], False, output_text))
        sdk_file = SimpleNamespace(type="file_citation", file_id="file_private", filename="guide.pdf", index=0)
        self.assertTrue(_valid_phase_two_output([message_output(output_text, [sdk_file])], False, output_text))
        self.assertFalse(_valid_phase_two_output([message_output(output_text, [
            SimpleNamespace(type="file_citation", file_id="", filename="guide.pdf"),
        ])], False, output_text))
        self.assertFalse(_valid_phase_two_output([{"type": "message", "status": "completed", "content": [
            {"type": "output_text", "text": output_text},
            {"type": "output_text", "text": output_text},
        ]}], False, output_text))
        self.assertFalse(_valid_phase_two_output([message_output("{}")], False, output_text))




class OpenAISecurityChatClientTest(unittest.TestCase):
    def _client(self, *responses, inventory=None, **kwargs):
        return OpenAISecurityChatClient(
            client=FakeOpenAI(*responses),
            model="gpt-test",
            followup_enabled=True,
            provider_ready=True,
            vector_store_id="vs_test",
            file_inventory=inventory,
            **kwargs,
        )

    def test_exact_two_calls_force_function_and_replay_without_previous_response_id(self):
        reasoning = {"type": "reasoning", "encrypted_content": "opaque-encrypted-item"}
        client = self._client(action_response(reasoning, function_call()), supplemental_response())
        result = client.ask(question="무엇을 해야 하나요?", analysis_result={"request_id": "r1", "overall_risk": {"level": "high"}}, history=[])
        calls = client.client.responses.calls
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["tools"][0]["name"], FUNCTION_NAME)
        self.assertEqual(calls[0]["tool_choice"], {"type": "function", "name": FUNCTION_NAME})
        self.assertFalse(calls[0]["parallel_tool_calls"])
        self.assertEqual(calls[0]["max_output_tokens"], 512)
        self.assertFalse(calls[0]["store"])
        self.assertNotIn("previous_response_id", calls[1])
        self.assertEqual(calls[1]["input"][-3], reasoning)
        self.assertEqual(calls[1]["input"][-1]["type"], "function_call_output")
        self.assertEqual(calls[1]["max_tool_calls"], 5)
        self.assertEqual(calls[1]["max_output_tokens"], 1536)
        self.assertFalse(calls[1]["store"])
        self.assertEqual(result["function_status"], "completed")
        self.assertNotIn("response_id", result)
        self.assertEqual(calls[1]["text"]["format"]["type"], "json_schema")
        self.assertTrue(calls[1]["text"]["format"]["strict"])
        self.assertEqual(calls[1]["text"]["format"]["schema"]["properties"]["schema_version"]["const"], "safemate.supplemental.v2")
        self.assertEqual(result["schema_version"], "safemate.followup.v2")
        self.assertNotIn("opaque-encrypted-item", repr(result))
        self.assertNotIn("call_1", repr(result))
        self.assertEqual(calls[0]["timeout"], 20.0)
        self.assertEqual(calls[1]["timeout"], 20.0)

    def test_rejects_closed_phase_one_contract_before_second_call(self):
        invalid_outputs = (
            action_response(function_call(name="wrong_name")),
            action_response(function_call(status="in_progress")),
            action_response(function_call(call_id="")),
            action_response(function_call(), function_call(call_id="call_2")),
            action_response(function_call(arguments=[])),
            action_response(function_call(arguments={})),
            action_response(function_call_raw("{")),
            action_response(function_call_raw("")),
            action_response(function_call_raw("null")),
            action_response(function_call(), {"type": "message", "status": "completed"}),
        )
        for response in invalid_outputs:
            with self.subTest(response=response):
                client = self._client(response)
                result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
                self.assertEqual(len(client.client.responses.calls), 1)
                self.assertEqual(result["fallback"], "function_rejected")
                self.assertIsNone(result["action_plan"])

    def test_rejects_provider_shape_drift_and_preserves_host_plan(self):
        client = self._client(action_response(function_call()), {"status": "failed", "output": []})
        result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(result["fallback"], "response_shape_drift")
        self.assertTrue(result["action_plan"]["classification_unchanged"])
        self.assertEqual(result["supplemental_claims"], [])
    def test_web_only_success_degrades_when_file_capability_is_unavailable(self):
        client = self._client(
            action_response(function_call()),
            supplemental_response(),
            inventory={"ready": False, "fresh": True, "files": []},
        )
        result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertIsNone(result["fallback"])
        self.assertTrue(result["degraded"])
        self.assertEqual(result["tool_status"], {"web": "unselected", "file": "unavailable"})
        self.assertEqual(result["file_status_reason"], "inventory_not_ready")
    def test_unoffered_file_call_does_not_override_file_capability_base(self):
        payload = '{"schema_version":"safemate.supplemental.v2","claims":[]}'
        response = {
            "status": "completed",
            "output_text": payload,
            "output": [
                {"type": "file_search_call", "status": "completed"},
                message_output(payload),
            ],
        }
        client = self._client(
            action_response(function_call()),
            response,
            inventory={"ready": False, "fresh": True, "files": []},
        )
        result = client.ask(
            question="도움",
            analysis_result={"overall_risk": {"level": "low"}},
            history=[],
        )
        self.assertEqual(result["fallback"], "response_shape_drift")
        self.assertEqual(result["tool_status"], {"web": "unselected", "file": "unavailable"})
        self.assertEqual(result["file_status_reason"], "inventory_not_ready")

    def test_post_response_fallbacks_preserve_observed_independent_tool_states(self):
        payload = '{"schema_version":"safemate.supplemental.v2","claims":[]}'
        citation_payload = json.dumps({
            "schema_version": "safemate.supplemental.v2",
            "claims": [{"text": "공식 안내", "source_scope": "web", "file_refs": []}],
        }, ensure_ascii=False)
        cases = (
            ("response_shape_drift", {"status": "completed", "output_text": payload, "output": [
                {"type": "web_search_call", "status": "completed"},
                {"type": "message", "status": "completed", "content": []},
            ]}, "completed"),
            ("supplemental_rejected", {"status": "completed", "output_text": "{}", "output": [
                {"type": "web_search_call", "status": "failed"}, message_output("{}"),
            ]}, "failed"),
            ("hosted_tool_failed", {"status": "completed", "output_text": payload, "output": [
                {"type": "web_search_call", "status": "failed"}, message_output(payload),
            ]}, "failed"),
            ("citation_rejected", {"status": "completed", "output_text": citation_payload, "output": [
                {"type": "web_search_call", "status": "completed", "sources": []},
                message_output(citation_payload, []),
            ]}, "completed"),
        )
        inventory = {"ready": True, "fresh": True, "files": [{"filename": "guide.pdf"}]}
        for fallback, response, web_status in cases:
            with self.subTest(fallback=fallback):
                client = self._client(action_response(function_call()), response, inventory=inventory)
                result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
                self.assertEqual(result["fallback"], fallback)
                self.assertEqual(result["tool_status"], {"web": web_status, "file": "unselected"})

    def test_readiness_bounded_operation_handles_completion_exception_and_timeout(self):
        ready = self._client(action_response(function_call()), supplemental_response())
        with patch("src.services.openai_client._bounded_readiness", wraps=_bounded_readiness) as bounded:
            ready.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(bounded.call_args.args[1], 5.0)

        failing = self._client()
        failing._provider_contract_ready = lambda: (_ for _ in ()).throw(RuntimeError("broken"))
        result = failing.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(result["fallback"], "provider_contract_unavailable")

        timed_out = self._client()
        with patch("src.services.openai_client._bounded_readiness", return_value=None):
            result = timed_out.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(result["fallback"], "preflight_readiness_timeout")
        self.assertEqual(timed_out.client.responses.calls, [])
    def test_readiness_single_flight_does_not_accumulate_stalled_workers(self):
        started = threading.Event()
        release = threading.Event()
        workers = []

        def blocking():
            workers.append(object())
            started.set()
            release.wait()
            return True

        began = time.monotonic()
        self.assertIsNone(_bounded_readiness(blocking, 0.01))
        self.assertLess(time.monotonic() - began, 0.5)
        self.assertTrue(started.wait(0.5))
        self.assertIsNone(_bounded_readiness(lambda: True, 0.01))
        self.assertEqual(len(workers), 1)
        release.set()
        for _ in range(50):
            if _bounded_readiness(lambda: True, 0.01) is True:
                break
            time.sleep(0.001)
        else:
            self.fail("readiness worker did not release its single-flight lock")

    def test_phase_two_input_limit_reports_unchecked_file_capability(self):
        client = self._client(action_response(function_call()))
        with patch("src.services.openai_client.MAX_PHASE_TWO_INPUT_BYTES", 0):
            result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(result["fallback"], "phase_two_input_limit")
        self.assertEqual(result["tool_status"]["file"], "unavailable")
        self.assertEqual(result["file_status_reason"], "not_checked")
        no_file = OpenAISecurityChatClient(
            client=FakeOpenAI(action_response(function_call())),
            model="gpt-test",
            followup_enabled=True,
            provider_ready=True,
            vector_store_id="",
        )
        with patch("src.services.openai_client.MAX_PHASE_TWO_INPUT_BYTES", 0):
            result = no_file.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(result["tool_status"]["file"], "not_configured")
        self.assertEqual(result["file_status_reason"], "not_configured")

    def test_inventory_exception_reports_a_non_sensitive_reason(self):
        def inventory(*, deadline_seconds, remaining_seconds):
            raise RuntimeError("private provider detail")
        inventory._safemate_deadline_aware = True
        client = self._client(action_response(function_call()), supplemental_response(), inventory=inventory)
        result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertIsNone(result["fallback"])
        self.assertEqual(result["file_status_reason"], "inventory_exception")

    def test_file_is_omitted_until_fresh_ready_inventory(self):
        client = self._client(action_response(function_call()), supplemental_response(), inventory={"ready": True, "fresh": False, "files": [{"filename": "guide.pdf"}]})
        client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual([tool["type"] for tool in client.client.responses.calls[1]["tools"]], ["web_search"])
    def test_default_attested_inventory_uses_authoritative_receipt_vector_digest(self):
        sdk_version = __import__("openai").__version__
        fake = FakeOpenAI(
            action_response(function_call()),
            supplemental_response(),
            vector_pages=[{"data": [{"file_id": "file_private", "status": "completed"}], "has_more": False, "last_id": None}],
        )
        with tempfile.TemporaryDirectory() as directory:
            environment = _write_provider_artifacts(directory, model="gpt-test", sdk_version=sdk_version)
            with patch.dict("os.environ", environment, clear=True):
                client = OpenAISecurityChatClient(
                    client=fake, model="gpt-test", followup_enabled=True, vector_store_id="vs_test"
                )
                self.assertEqual(fake.vector_files.calls, [])
                client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual([tool["type"] for tool in fake.responses.calls[1]["tools"]], ["web_search", "file_search"])
        self.assertEqual(len(fake.vector_files.calls), 1)
    def test_default_attested_inventory_is_deadline_aware_and_fails_closed_before_vector_io(self):
        sdk_version = __import__("openai").__version__
        fake = FakeOpenAI(
            vector_pages=[{"data": [{"file_id": "file_private", "status": "completed"}], "has_more": False, "last_id": None}],
        )
        with tempfile.TemporaryDirectory() as directory:
            environment = _write_provider_artifacts(directory, model="gpt-test", sdk_version=sdk_version)
            with patch.dict("os.environ", environment, clear=True):
                client = OpenAISecurityChatClient(
                    client=fake, model="gpt-test", followup_enabled=True, vector_store_id="vs_test"
                )
                inventory = client._file_inventory
                self.assertTrue(getattr(inventory, "_safemate_deadline_aware", False))
                self.assertFalse(
                    inventory(deadline_seconds=1.0, remaining_seconds=lambda: 0.0)["ready"]
                )
        self.assertEqual(fake.vector_files.calls, [])

    def test_citation_failure_discards_all_supplemental_claims(self):
        claim = {"text": "공식 안내를 확인하세요.", "source_scope": "web", "file_refs": []}
        # An orphan annotation has no completed matching Web source and is rejected globally.
        output = [{"type": "message", "content": [{"type": "output_text", "annotations": [{"type": "url_citation", "url": "https://www.kisa.or.kr/a", "title": "KISA", "start_index": 0, "end_index": 5}]}]}]
        client = self._client(action_response(function_call()), supplemental_response([claim], output))
        result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(result["fallback"], "response_shape_drift")
        self.assertEqual(result["supplemental_claims"], [])
        self.assertEqual(result["citations"], [])

    def test_missing_or_tampered_provider_trust_fails_before_any_responses_call(self):
        for tamper in ("missing", "bytes", "digest"):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as directory:
                environment = _write_provider_artifacts(
                    directory, model="gpt-test", sdk_version=__import__("openai").__version__
                )
                if tamper == "missing":
                    environment = {}
                elif tamper == "bytes":
                    Path(environment["OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH"]).write_bytes(b"{}")
                else:
                    environment["OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256"] = "0" * 64
                fake = FakeOpenAI()
                with patch.dict("os.environ", environment, clear=True):
                    client = OpenAISecurityChatClient(client=fake, model="gpt-test", followup_enabled=True)
                    result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
                self.assertEqual(fake.responses.calls, [])
                self.assertEqual(result["fallback"], "provider_contract_unavailable")
                self.assertIsNone(result["action_plan"])
    def test_default_enabled_client_does_not_construct_sdk_without_trust_anchors(self):
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "offline-key", "OPENAI_MODEL": "gpt-test"},
            clear=True,
        ), patch("src.services.openai_client.OpenAI") as constructor:
            client = OpenAISecurityChatClient(followup_enabled=True)
        self.assertIsNone(client.client)
        constructor.assert_not_called()

    def test_public_result_never_exposes_provider_identifiers(self):
        phase_two = supplemental_response()
        phase_two["id"] = "resp_provider"
        phase_two["output"] = [{"type": "message", "file_id": "file_provider", "vector_store_id": "vs_test", "content": []}]
        fake = FakeOpenAI(action_response({"type": "reasoning", "encrypted_content": "secret-reasoning"}, function_call()), phase_two)
        client = self._client()
        client.client = fake
        result = client.ask(question="도움", analysis_result={"request_id": "host-request", "overall_risk": {"level": "low"}}, history=[])
        public = json.dumps(result, ensure_ascii=False)
        for provider_value in ("secret-reasoning", "call_1", "resp_provider", "file_provider", "vs_test"):
            self.assertNotIn(provider_value, public)

    def test_disabled_never_calls_provider_and_blank_question_fails_first(self):
        fake = FakeOpenAI()
        client = OpenAISecurityChatClient(client=fake, model="gpt-test", followup_enabled=False)
        result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(fake.responses.calls, [])
        self.assertEqual(result["fallback"], "disabled")
        with self.assertRaises(ValueError):
            client.ask(question=" ", analysis_result={}, history=[])

    def test_history_limits_drop_oldest_whole_messages(self):
        client = self._client(
            action_response(function_call()),
            supplemental_response(),
        )
        history = [
            {"role": "user", "content": f"message-{index}"}
            for index in range(25)
        ]

        client.ask(
            question="도움",
            analysis_result={"request_id": "host-request", "overall_risk": {"level": "low"}},
            history=history,
        )

        retained = client.client.responses.calls[0]["input"][1:-1]
        self.assertEqual(len(retained), 20)
        self.assertEqual(retained[0]["content"], "message-5")
        self.assertEqual(retained[-1]["content"], "message-24")

    def test_history_byte_limit_keeps_newest_messages(self):
        client = self._client(
            action_response(function_call()),
            supplemental_response(),
        )
        history = [
            {"role": "assistant", "content": "가" * 2000}
            for _ in range(20)
        ]

        client.ask(
            question="도움",
            analysis_result={"request_id": "host-request", "overall_risk": {"level": "low"}},
            history=history,
        )

        retained = client.client.responses.calls[0]["input"][1:-1]
        self.assertEqual(len(retained), 8)

    def test_unmarked_injected_callbacks_are_not_invoked(self):
        ready_called = False
        inventory_called = False

        def readiness():
            nonlocal ready_called
            ready_called = True
            return True

        def inventory():
            nonlocal inventory_called
            inventory_called = True
            return {"ready": True, "fresh": True, "files": []}

        provider = FakeOpenAI()
        blocked = OpenAISecurityChatClient(
            client=provider,
            model="gpt-test",
            followup_enabled=True,
            provider_ready=readiness,
        ).ask(
            question="도움",
            analysis_result={"overall_risk": {"level": "low"}},
            history=[],
        )
        self.assertEqual(blocked["fallback"], "provider_contract_unavailable")
        self.assertFalse(ready_called)
        self.assertEqual(provider.responses.calls, [])

        client = self._client(
            action_response(function_call()),
            supplemental_response(),
            inventory=inventory,
        )
        client.ask(
            question="도움",
            analysis_result={"request_id": "host-request", "overall_risk": {"level": "low"}},
            history=[],
        )
        self.assertFalse(inventory_called)
    def test_deadline_exhaustion_before_phase_one_skips_responses(self):
        clock = ScriptedClock(0, 0, 0, 0, 0, 45)
        client = self._client(monotonic=clock)
        result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(client.client.responses.calls, [])
        self.assertEqual(result["fallback"], "function_request_failed")

    def test_deadline_exhaustion_after_phase_one_uses_function_fallback(self):
        clock = ScriptedClock(0, 0, 0, 0, 0, 0, 0, 45)
        client = self._client(action_response(function_call()), monotonic=clock)
        result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(len(client.client.responses.calls), 1)
        self.assertEqual(result["fallback"], "function_request_failed")
        self.assertIsNone(result["action_plan"])

    def test_phase_one_emit_cannot_start_request_after_deadline(self):
        clock = AdvancingClock()

        def telemetry(event):
            if event["phase"] == "phase_one" and event["state"] == "started":
                clock.advance(45)

        client = self._client(monotonic=clock, telemetry_sink=telemetry)
        result = client.ask(
            question="도움",
            analysis_result={"overall_risk": {"level": "low"}},
            history=[],
        )

        self.assertEqual(client.client.responses.calls, [])
        self.assertEqual(result["fallback"], "function_request_failed")

    def test_inventory_deadline_exhaustion_preserves_action_plan(self):
        clock = AdvancingClock()

        def inventory(*, deadline_seconds, remaining_seconds):
            clock.advance(45)
            return {"ready": True, "fresh": True, "files": [{"filename": "guide.pdf"}]}

        inventory._safemate_deadline_aware = True

        client = self._client(action_response(function_call()), inventory=inventory, monotonic=clock)
        result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(len(client.client.responses.calls), 1)
        self.assertEqual(result["fallback"], "deadline_exhausted")
        self.assertIsNotNone(result["action_plan"])
        self.assertEqual(result["supplemental_status"], "discarded")
        self.assertEqual(result["tool_status"]["file"], "unavailable")
        self.assertEqual(result["file_status_reason"], "deadline_exhausted")

    def test_deadline_aware_inventory_receives_remaining_readiness_budget(self):
        observed = []

        def inventory(*, deadline_seconds, remaining_seconds):
            observed.append((deadline_seconds, remaining_seconds()))
            return {"ready": False, "fresh": True, "files": []}

        inventory._safemate_deadline_aware = True
        client = self._client(
            action_response(function_call()),
            supplemental_response(),
            inventory=inventory,
        )

        client.ask(
            question="도움",
            analysis_result={"request_id": "host-request", "overall_risk": {"level": "low"}},
            history=[],
        )

        self.assertEqual(observed[0][0], 5.0)
        self.assertGreater(observed[0][1], 0)
        self.assertLessEqual(observed[0][1], 45.0)

    def test_phase_two_deadline_fallback_reports_hosted_transition(self):
        clock = AdvancingClock()
        events = []

        def telemetry(event):
            events.append(event)
            if event["phase"] == "phase_two" and event["state"] == "started":
                clock.advance(45)

        client = self._client(
            action_response(function_call()),
            monotonic=clock,
            telemetry_sink=telemetry,
        )
        result = client.ask(
            question="도움",
            analysis_result={"request_id": "host-request", "overall_risk": {"level": "low"}},
            history=[],
        )
        self.assertEqual(result["fallback"], "deadline_exhausted")
        self.assertEqual(
            [(event["state"], event["tool"]) for event in events if event["phase"] == "phase_two"],
            [("started", "hosted"), ("fallback", "hosted")],
        )

    def test_deadline_before_phase_two_skips_hosted_evidence(self):
        clock = ScriptedClock(*([0] * 12), 45)
        client = self._client(action_response(function_call()), monotonic=clock)
        result = client.ask(question="도움", analysis_result={"overall_risk": {"level": "low"}}, history=[])
        self.assertEqual(len(client.client.responses.calls), 1)
        self.assertEqual(result["fallback"], "deadline_exhausted")
        self.assertIsNotNone(result["action_plan"])


if __name__ == "__main__":
    unittest.main()
