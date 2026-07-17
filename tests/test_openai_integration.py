"""Cost-bounded, opt-in verification of the real OpenAI Responses wire contract."""

from __future__ import annotations

import copy
import json
import os
import time
from types import SimpleNamespace
from typing import Any

import pytest


pytestmark = pytest.mark.openai_integration

_MAX_ATTEMPTS = 4
_MAX_REQUEST_SECONDS = 20
_MAX_SUITE_SECONDS = 120
_MAX_SERIALIZED_INPUT_BYTES = 48 * 1024
_MAX_REPORTED_INPUT_TOKENS = 12_000
_MAX_REPORTED_OUTPUT_TOKENS = 2_560


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _as_mapping(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return copy.deepcopy(response)
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        return copy.deepcopy(dump(mode="json"))
    raise AssertionError("provider response does not support safe shape inspection")


def _usage_value(response: Any, name: str) -> int:
    usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else -1


def _has_valid_usage(response: Any) -> bool:
    return all(_usage_value(response, name) >= 0 for name in ("input_tokens", "output_tokens"))
def _value(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _output(response: Any) -> list[Any]:
    value = _value(response, "output", [])
    return value if isinstance(value, list) else []



class _BoundedResponses:
    """Proxy that makes the selected suite's four-attempt ceiling executable."""

    def __init__(self, responses: Any, started: float) -> None:
        self._responses = responses
        self._started = started
        self.calls: list[dict[str, Any]] = []
        self.results: list[Any] = []
        self.input_bytes = 0

    def create(self, **kwargs: Any) -> Any:
        _require(time.monotonic() - self._started <= _MAX_SUITE_SECONDS, "live suite deadline exceeded")
        _require(len(self.calls) < _MAX_ATTEMPTS, "Responses attempt budget exceeded")
        _require(kwargs.get("max_output_tokens") in {512, 1536}, "invalid max_output_tokens")
        _require(kwargs.get("max_tool_calls") in {1, 5}, "invalid max_tool_calls")
        encoded = json.dumps(kwargs.get("input"), ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        _require(self.input_bytes + len(encoded) <= _MAX_SERIALIZED_INPUT_BYTES, "serialized input budget exceeded")
        self.input_bytes += len(encoded)
        self.calls.append(kwargs)
        started = time.monotonic()
        try:
            response = self._responses.create(**kwargs)
        except Exception:
            raise AssertionError("Responses request failed") from None
        _require(time.monotonic() - started <= _MAX_REQUEST_SECONDS, "Responses request deadline exceeded")
        _require(_has_valid_usage(response), "provider response omitted valid usage")
        self.results.append(response)
        return response

    def assert_budget(self) -> None:
        _require(len(self.calls) == _MAX_ATTEMPTS, "selected suite did not make exactly four Responses attempts")
        _require(time.monotonic() - self._started <= _MAX_SUITE_SECONDS, "live suite deadline exceeded")
        hosted_calls = sum(
            1
            for response in self.results
            for item in _output(response)
            if _value(item, "type") in {"web_search_call", "file_search_call"}
        )
        _require(hosted_calls <= 4, "hosted-tool call budget exceeded")
        _require(sum(_usage_value(item, "input_tokens") for item in self.results) <= _MAX_REPORTED_INPUT_TOKENS, "reported input-token budget exceeded")
        _require(sum(_usage_value(item, "output_tokens") for item in self.results) <= _MAX_REPORTED_OUTPUT_TOKENS, "reported output-token budget exceeded")


@pytest.fixture(scope="module")
def live_harness() -> tuple[Any, _BoundedResponses, dict[str, Any]]:
    # This fixture is never entered unless conftest's three gates and CI trust gate passed.
    required = ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_VECTOR_STORE_ID", "OPENAI_INTEGRATION_FILE_NAME")
    if any(not os.getenv(name, "").strip() for name in required):
        pytest.skip("live prerequisites are incomplete; API key, model, Vector store, and attested filename are required")

    from openai import OpenAI
    from src.services.openai_client import OpenAISecurityChatClient

    started = time.monotonic()
    sdk = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=_MAX_REQUEST_SECONDS, max_retries=0)
    responses = _BoundedResponses(sdk.responses, started)
    filename = os.environ["OPENAI_INTEGRATION_FILE_NAME"].strip()
    inventory = {"ready": True, "fresh": True, "files": [{"filename": filename}]}
    product = OpenAISecurityChatClient(
        client=SimpleNamespace(responses=responses),
        model=os.environ["OPENAI_MODEL"].strip(),
        vector_store_id=os.environ["OPENAI_VECTOR_STORE_ID"].strip(),
        followup_enabled=True,
        provider_ready=True,
        file_inventory=inventory,
    )
    try:
        yield product, responses, inventory
    finally:
        try:
            responses.assert_budget()
        finally:
            sdk.close()


def _assert_wire_shape(calls: list[dict[str, Any]], results: list[Any], offset: int) -> None:
    first, second = calls[offset : offset + 2]
    _require(first.get("store") is False and second.get("store") is False, "Responses storage must remain disabled")
    _require(first.get("parallel_tool_calls") is False, "phase one must disable parallel tools")
    _require(first.get("tool_choice") == {"type": "function", "name": "build_security_action_plan"}, "phase one must force the custom function")
    _require(first.get("max_output_tokens") == 512 and first.get("max_tool_calls") == 1, "phase one limits must be explicit")
    _require(second.get("max_output_tokens") == 1536 and second.get("max_tool_calls") == 5, "phase two limits must be explicit")
    _require(first.get("include") == ["reasoning.encrypted_content"], "phase one must request encrypted reasoning replay")
    _require("previous_response_id" not in second, "phase two must use stateless replay")
    _require(second.get("tool_choice") == "auto", "phase two must auto-select hosted tools")
    _require({tool.get("type") for tool in second.get("tools", [])} == {"web_search", "file_search"}, "phase two must offer only hosted Web and File Search")
    phase_one_output = _output(results[offset])
    replayed_reasoning = [item for item in phase_one_output if _value(item, "type") == "reasoning"]
    _require(bool(replayed_reasoning), "phase one did not return encrypted reasoning")
    _require(all(isinstance(_value(item, "encrypted_content"), str) and _value(item, "encrypted_content") for item in replayed_reasoning), "phase one reasoning was not encrypted")
    _require(sum(_value(item, "type") == "function_call" and _value(item, "name") == "build_security_action_plan" and _value(item, "status") == "completed" for item in phase_one_output) == 1, "phase one did not complete exactly one forced function call")
    phase_two_input = second.get("input", [])
    _require(all(item in phase_two_input for item in replayed_reasoning), "phase two did not replay encrypted reasoning")
    _require(sum(_value(item, "type") == "function_call_output" for item in phase_two_input) == 1, "turn must dispatch exactly one function output")


def _failed_tool_shape(response: dict[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(response)
    for item in changed.get("output", []):
        if item.get("type") in {"web_search_call", "file_search_call"}:
            item["status"] = "failed"
            return changed
    raise AssertionError("live response did not contain a hosted tool call")


def _missing_citation_shape(response: dict[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(response)
    for item in changed.get("output", []):
        for part in item.get("content", []) if item.get("type") == "message" else []:
            if part.get("type") == "output_text":
                part["annotations"] = []
    return changed


def test_real_responses_two_turn_contract(live_harness: tuple[Any, _BoundedResponses, dict[str, Any]]) -> None:
    product, responses, inventory = live_harness
    web_question = "분류는 바꾸지 말고, 공식 KISA 웹 안내를 근거로 지금 취할 안전 조치를 확인해 주세요."
    file_question = "분류는 바꾸지 말고, 등록된 참고 문서를 근거로 지금 취할 안전 조치를 확인해 주세요."
    web_analysis = {"request_id": "live-web", "overall_risk": {"level": "high"}}
    file_analysis = {"request_id": "live-file", "overall_risk": {"level": "high"}}

    web_result = product.ask(question=web_question, analysis_result=web_analysis, history=[])
    file_result = product.ask(question=file_question, analysis_result=file_analysis, history=[])

    _assert_wire_shape(responses.calls, responses.results, 0)
    _assert_wire_shape(responses.calls, responses.results, 2)
    for result in (web_result, file_result):
        _require(result.get("function_status") == "completed", "forced custom function did not complete")
        _require(result.get("supplemental_status") == "completed", "hosted supplemental response was not accepted")
        _require(result.get("citation_status") == "accepted", "hosted evidence citations were not accepted")
        from src.services.web_search import is_official_source_url
        _require(all(is_official_source_url(citation.get("url")) for citation in result["citations"] if citation.get("type") == "url"), "Web citation was not an approved official-domain URL")
    _require(any(citation.get("type") == "url" for citation in web_result["citations"]), "Web-focused turn omitted Web evidence")
    _require(any(citation.get("type") == "file" for citation in file_result["citations"]), "File-focused turn omitted File evidence")

    class ReplayResponses:
        def __init__(self, *items: dict[str, Any]) -> None:
            self.items = list(items)

        def create(self, **_: Any) -> dict[str, Any]:
            return self.items.pop(0)

    from src.services.openai_client import OpenAISecurityChatClient

    phase_one = _as_mapping(responses.results[0])
    phase_two = _as_mapping(responses.results[1])
    for mutation, expected_fallback in (
        (_failed_tool_shape, "hosted_tool_failed"),
        (_missing_citation_shape, "citation_rejected"),
    ):
        replay = OpenAISecurityChatClient(
            client=SimpleNamespace(responses=ReplayResponses(copy.deepcopy(phase_one), mutation(phase_two))),
            model="replay-test",
            followup_enabled=True,
            provider_ready=True,
            vector_store_id="vs_test",
            file_inventory=inventory,
        )
        failed = replay.ask(question=web_question, analysis_result=web_analysis, history=[])
        _require(failed.get("fallback") == expected_fallback, f"{expected_fallback} must fail closed through ask")
        _require(failed.get("supplemental_claims") == [] and failed.get("citations") == [], "mutated replay leaked evidence")
