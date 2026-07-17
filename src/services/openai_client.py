"""Bounded, stateless OpenAI follow-up flow for completed security analyses."""

from __future__ import annotations

import json
from dataclasses import dataclass
import os
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from dotenv import load_dotenv
import openai
from openai import OpenAI

from src.config import (
    OPENAI_FOLLOWUP_READINESS_TIMEOUT_SECONDS,
    OPENAI_FOLLOWUP_TURN_TIMEOUT_SECONDS,
    OPENAI_TIMEOUT_SECONDS,
    is_openai_followup_enabled,
)
from src.services.provider_attestation import AttestationError, health as attestation_health
from src.services.file_search import (
    FILE_SEARCH_INCLUDE,
    admit_file_citations,
    build_attested_file_inventory_provider,
    build_file_search_tool,
    is_file_search_call,
)
from src.services.security_action import (
    CUSTOM_FUNCTION_TOOL,
    FUNCTION_NAME,
    SecurityActionDispatcher,
    canonical_action_plan_json,
    normalize_reported_event,
    validate_action_arguments,
    validate_action_context,
    validate_phase_one_response,
)
from src.services.web_search import WEB_SEARCH_INCLUDE, admit_web_citations, build_web_search_tool, is_web_search_call
from src.services.followup_telemetry import FollowupTelemetry, MAX_TOKEN_COUNT, corpus_version

ANALYSIS_SNAPSHOT_FIELDS = (
    "schema_version", "request_id", "input_type", "status", "overall_risk", "summary",
    "risk_reasons", "recommended_actions", "message_analysis", "url_analysis_summary",
    "url_analysis", "web_evidence", "file_evidence", "limitations", "errors",
)
MAX_CHAT_HISTORY_MESSAGES = 20
MAX_CHAT_HISTORY_CHARS = 40_000
MAX_CHAT_HISTORY_BYTES = 48 * 1024
MAX_CHAT_QUESTION_CHARS = 4_000
MAX_FUNCTION_ARGUMENT_BYTES = 1024
MAX_PHASE_ONE_INPUT_BYTES = 64 * 1024
MAX_PHASE_TWO_INPUT_BYTES = 72 * 1024
MAX_RESPONSE_OUTPUT_ITEMS = 16
MAX_ANALYSIS_SNAPSHOT_BYTES = 16 * 1024
MAX_ANALYSIS_SNAPSHOT_DEPTH = 6
MAX_ANALYSIS_SNAPSHOT_NODES = 512
MAX_ANALYSIS_SNAPSHOT_LIST_ITEMS = 50
MAX_OUTPUT_TEXT_ANNOTATIONS = 32
MAX_ANNOTATION_URL_BYTES = 2048
MAX_ANNOTATION_TITLE_BYTES = 512
MAX_ANNOTATION_FILE_BYTES = 512
SUPPLEMENTAL_SCHEMA = "safemate.supplemental.v2"
PUBLIC_SCHEMA = "safemate.followup.v2"
SUPPLEMENTAL_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "claims"],
    "properties": {
        "schema_version": {"type": "string", "const": SUPPLEMENTAL_SCHEMA},
        "claims": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "source_scope", "file_refs"],
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 600},
                    "source_scope": {"type": "string", "enum": ["web", "file", "mixed"]},
                    "file_refs": {"type": "array", "maxItems": 3, "items": {"type": "integer", "minimum": 0}},
                },
            },
        },
    },
}
_READINESS_SINGLE_FLIGHT = threading.Lock()



SECURITY_ASSISTANT_INSTRUCTIONS = """You are SafeMate's security follow-up assistant. The first-stage analysis is frozen.
Return no prose in phase one: call build_security_action_plan exactly once. In phase two return only a strict JSON object with schema_version safemate.supplemental.v2 and ordered supplemental claims. Never change classification."""


@dataclass(frozen=True)
class FileCapability:
    status: str
    reason: str

    @property
    def offered(self) -> bool:
        return self.status == "ready"

def build_analysis_snapshot(analysis_result: dict) -> dict:
    """Return the bounded approved analysis projection for the post-analysis chat stage."""
    if not isinstance(analysis_result, dict):
        raise TypeError("analysis_result must be a dictionary")
    snapshot = {key: analysis_result[key] for key in ANALYSIS_SNAPSHOT_FIELDS if key in analysis_result}
    _validate_snapshot(snapshot)
    return snapshot


class OpenAISecurityChatClient:
    """One-persona, two-Responses-call assistant with host-owned action policy."""

    def __init__(
        self, *, client: Any | None = None, model: str | None = None,
        vector_store_id: str | None = None, followup_enabled: bool | None = None,
        provider_ready: bool | Callable[[], bool] | None = None,
        file_inventory: Mapping[str, Any] | Callable[[], Mapping[str, Any] | None] | None = None,
        file_inventory_provider: Callable[[], Mapping[str, Any] | None] | None = None,
        telemetry_sink: Callable[[Mapping[str, Any]], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        load_dotenv()
        self.model = (model or os.getenv("OPENAI_MODEL") or "gpt-5.6").strip()
        configured_store = vector_store_id if vector_store_id is not None else os.getenv("OPENAI_VECTOR_STORE_ID")
        self.vector_store_id = configured_store.strip() if isinstance(configured_store, str) and configured_store.strip() else None
        self._enabled = _enabled_from_env() if followup_enabled is None else followup_enabled is True
        self._provider_ready = provider_ready
        # Construct only for an explicitly enabled, fully configured capability.
        self.client = client
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        configured_model = os.getenv("OPENAI_MODEL", "").strip()
        trust_configured = bool(
            os.getenv("OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH", "").strip()
            and os.getenv(
                "OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256", ""
            ).strip()
        )
        if (
            self._enabled
            and self.client is None
            and api_key
            and configured_model
            and trust_configured
        ):
            self.client = OpenAI(
                api_key=api_key,
                timeout=min(OPENAI_TIMEOUT_SECONDS, 20),
                max_retries=0,
            )
        if file_inventory_provider is not None:
            self._file_inventory = file_inventory_provider
        elif file_inventory is not None:
            self._file_inventory = file_inventory
        elif self._enabled and self.client is not None and self.vector_store_id is not None:
            self._file_inventory = _default_file_inventory_provider(
                self.client, self.vector_store_id, self.model
            )
        else:
            self._file_inventory = _default_file_inventory

        self._telemetry_sink = telemetry_sink
        self._monotonic = monotonic or time.monotonic

    def ask(self, *, question: str, analysis_result: dict, history: list[dict]) -> dict:
        question = _validate_question(question)
        snapshot = build_analysis_snapshot(analysis_result)
        sanitized_history = _sanitize_history(history)
        messages = _build_messages(snapshot, sanitized_history, question)
        if _json_bytes(messages) > MAX_PHASE_ONE_INPUT_BYTES:
            raise ValueError("follow-up input exceeds the safe size limit")
        telemetry = FollowupTelemetry(self._telemetry_sink)
        started_at = self._monotonic()

        def emit(
            phase: str, state: str, reason: str = "none", *, attempt: int = 1, tool: str = "none",
            fallback: str = "none", inventory: Mapping[str, Any] | None = None,
            result_count: int = 0, claim_count: int = 0, tool_count: int = 0, token_count: int = 0,
        ) -> None:
            telemetry.emit(
                phase=phase, attempt=attempt, state=state, reason=reason, tool=tool, fallback=fallback,
                duration_ms=min(120_000, max(0, int((self._monotonic() - started_at) * 1000))),
                model=self.model, token_count=token_count, result_count=result_count, claim_count=claim_count,
                tool_count=tool_count, vector_state=_telemetry_vector_state(inventory, self.vector_store_id),
                corpus_version=_telemetry_corpus_version(inventory),
            )
        def remaining_seconds() -> float:
            return started_at + OPENAI_FOLLOWUP_TURN_TIMEOUT_SECONDS - self._monotonic()

        def operation_timeout(limit: float) -> float | None:
            remaining = remaining_seconds()
            return min(limit, remaining) if remaining > 0 else None

        def readiness_available() -> tuple[bool, str | None]:
            timeout = operation_timeout(OPENAI_FOLLOWUP_READINESS_TIMEOUT_SECONDS)
            if timeout is None:
                return False, "deadline_exhausted"
            readiness_started = self._monotonic()
            ready = _bounded_readiness(self._provider_contract_ready, timeout)
            elapsed = self._monotonic() - readiness_started
            if ready is None or elapsed > OPENAI_FOLLOWUP_READINESS_TIMEOUT_SECONDS:
                return False, "readiness_timeout"
            if remaining_seconds() <= 0:
                return False, "deadline_exhausted"
            return ready, None

        def inventory_available() -> tuple[Mapping[str, Any] | None, str | None]:
            inventory_started = self._monotonic()
            timeout = operation_timeout(OPENAI_FOLLOWUP_READINESS_TIMEOUT_SECONDS)
            if timeout is None:
                return None, "deadline_exhausted"
            inventory, inventory_reason = self._inventory(timeout, remaining_seconds)
            elapsed = self._monotonic() - inventory_started
            if remaining_seconds() <= 0:
                return inventory, "deadline_exhausted"
            if elapsed > OPENAI_FOLLOWUP_READINESS_TIMEOUT_SECONDS:
                return inventory, "readiness_timeout"
            return inventory, inventory_reason

        def fallback(
            action_plan: dict | None, reason: str, *, phase: str, tool: str = "none",
            inventory: Mapping[str, Any] | None = None, file_capability: FileCapability | None = None,
        ) -> dict:
            emit(
                phase, "fallback", reason, attempt=2 if phase == "phase_two" else 1,
                tool=tool, fallback=reason, inventory=inventory,
            )
            return _fallback(action_plan, reason, file_capability=file_capability)

        if not self._enabled or self.client is None:
            return fallback(None, "disabled", phase="preflight")
        ready, readiness_reason = readiness_available()
        if not ready:
            if readiness_reason == "deadline_exhausted":
                return fallback(None, "function_request_failed", phase="phase_one", tool="function")
            return fallback(
                None,
                "preflight_readiness_timeout" if readiness_reason == "readiness_timeout"
                else "provider_contract_unavailable",
                phase="preflight",
            )
        emit("phase_one", "started", tool="function")
        phase_one_timeout = operation_timeout(OPENAI_TIMEOUT_SECONDS)
        if phase_one_timeout is None:
            return fallback(None, "function_request_failed", phase="phase_one", tool="function")
        try:
            phase_one = self._phase_one(messages, timeout=phase_one_timeout)
        except Exception:
            return fallback(None, "function_request_failed", phase="phase_one", tool="function")
        if remaining_seconds() <= 0:
            return fallback(None, "function_request_failed", phase="phase_one", tool="function")
        accepted = validate_phase_one_response(phase_one)
        if accepted is None:
            return fallback(None, "function_rejected", phase="function", tool="function")
        replay_items, function_call = accepted
        try:
            arguments = _parse_function_arguments(_value(function_call, "arguments"))
            if _json_bytes(arguments) > MAX_FUNCTION_ARGUMENT_BYTES:
                raise ValueError("arguments too large")
            request = normalize_reported_event(
                validate_action_arguments(arguments), question, sanitized_history
            )
            context = validate_action_context(snapshot.get("request_id"), _risk_level(snapshot))
            dispatcher = SecurityActionDispatcher(context)
            action_plan = dispatcher.dispatch(FUNCTION_NAME, request)
            action_json = canonical_action_plan_json(action_plan)
        except (TypeError, ValueError, json.JSONDecodeError, RuntimeError):
            return fallback(None, "function_rejected", phase="function", tool="function")
        emit("function", "completed", "completed", tool="function", token_count=_telemetry_token_count(phase_one))

        function_call_id = next(
            (
                item["call_id"]
                for item in replay_items
                if item.get("type") == "function_call"
            ),
            None,
        )
        if function_call_id is None:
            return fallback(None, "function_rejected", phase="function", tool="function")
        function_output = {
            "type": "function_call_output", "call_id": function_call_id, "output": action_json,
        }
        phase_two_input = [*messages, *replay_items, function_output]
        if _json_bytes(phase_two_input) > MAX_PHASE_TWO_INPUT_BYTES:
            capability = FileCapability(
                "not_configured" if self.vector_store_id is None else "unavailable",
                "not_configured" if self.vector_store_id is None else "not_checked",
            )
            return fallback(
                action_plan, "phase_two_input_limit", phase="phase_two", file_capability=capability,
            )
        inventory, readiness_reason = inventory_available()
        if readiness_reason == "deadline_exhausted":
            file_capability = _file_capability(
                inventory, self.vector_store_id, "deadline_exhausted"
            )
            return fallback(
                action_plan, readiness_reason, phase="phase_two", inventory=inventory,
                file_capability=file_capability,
            )
        tools, include, file_capability = self._phase_two_tools(inventory, readiness_reason)
        emit("phase_two", "started", attempt=2, tool="hosted", inventory=inventory, tool_count=len(tools))
        phase_two_timeout = operation_timeout(OPENAI_TIMEOUT_SECONDS)
        if phase_two_timeout is None:
            return fallback(
                action_plan, "deadline_exhausted", phase="phase_two", tool="hosted",
                inventory=inventory, file_capability=file_capability,
            )
        try:
            phase_two = self.client.responses.create(
                model=self.model, instructions=SECURITY_ASSISTANT_INSTRUCTIONS, input=phase_two_input,
                tools=tools, tool_choice="auto", include=include, max_tool_calls=5,
                max_output_tokens=1536, reasoning={"effort": "low"}, store=False,
                timeout=phase_two_timeout,
                text={"format": {"type": "json_schema", "name": "safemate_supplemental_v2", "strict": True, "schema": SUPPLEMENTAL_JSON_SCHEMA}},
            )
        except Exception:
            return fallback(action_plan, "hosted_request_failed", phase="phase_two", tool="hosted", inventory=inventory, file_capability=file_capability)
        if remaining_seconds() <= 0:
            return fallback(
                action_plan, "deadline_exhausted", phase="phase_two",
                tool="hosted", inventory=inventory, file_capability=file_capability,
            )
        result = self._supplemental_result(phase_two, action_plan, inventory, file_capability)
        output = _value(phase_two, "output", [])
        result_count = len(output) if isinstance(output, list) else 0
        claim_count = len(result["supplemental_claims"])
        if result["fallback"] is not None:
            reason = result["fallback"]
            phase = "citation" if reason == "citation_rejected" else "phase_two"
            emit(
                phase, "fallback", reason, attempt=2 if phase == "phase_two" else 1,
                tool="hosted", fallback=reason, inventory=inventory,
                result_count=result_count, claim_count=claim_count, tool_count=len(result["tools_used"]),
                token_count=_telemetry_token_count(phase_two),
            )
        else:
            emit("citation", "accepted", "completed", tool="hosted", inventory=inventory,
                 result_count=result_count, claim_count=claim_count, tool_count=len(result["tools_used"]),
                 token_count=_telemetry_token_count(phase_two))
        return result

    def _phase_one(self, messages: list[dict], *, timeout: float) -> Any:
        return self.client.responses.create(
            model=self.model, instructions=SECURITY_ASSISTANT_INSTRUCTIONS, input=messages,
            tools=[CUSTOM_FUNCTION_TOOL], tool_choice={"type": "function", "name": FUNCTION_NAME},
            parallel_tool_calls=False, include=["reasoning.encrypted_content"],
            max_output_tokens=512, reasoning={"effort": "low"}, store=False, timeout=timeout,
        )

    def _phase_two_tools(
        self, inventory: Mapping[str, Any] | None, readiness_reason: str | None = None
    ) -> tuple[list[dict], list[str], FileCapability]:
        tools, include = [build_web_search_tool()], [WEB_SEARCH_INCLUDE]
        capability = _file_capability(inventory, self.vector_store_id, readiness_reason)
        if capability.offered:
            tools.append(build_file_search_tool(self.vector_store_id))
            include.append(FILE_SEARCH_INCLUDE)
        return tools, include, capability

    def _inventory(
        self,
        deadline_seconds: float | None = None,
        remaining_seconds: Callable[[], float] | None = None,
    ) -> tuple[Mapping[str, Any] | None, str | None]:
        source = self._file_inventory
        try:
            if callable(source):
                if getattr(source, "_safemate_deadline_aware", False) is not True:
                    return None, None
                value = source(
                    deadline_seconds=deadline_seconds,
                    remaining_seconds=remaining_seconds,
                )
            else:
                value = source
        except Exception:
            return None, "inventory_exception"
        return (value, None) if isinstance(value, Mapping) else (None, None)

    def _provider_contract_ready(self) -> bool:
        if self._provider_ready is not None:
            return self._ready(self._provider_ready)
        return _default_provider_ready(self.model)

    @staticmethod
    def _ready(value: bool | Callable[[], bool]) -> bool:
        return value is True

    def _supplemental_result(self, response: Any, action_plan: dict, inventory: Mapping[str, Any] | None, file_capability: FileCapability) -> dict:
        file_offered = file_capability.offered
        output = _value(response, "output", [])
        tool_status = _observed_tool_status(output, file_capability)
        if _value(response, "status") != "completed" or not _valid_phase_two_output(
            output, file_offered, _value(response, "output_text", "")
        ):
            return _fallback(
                action_plan, "response_shape_drift", file_capability=file_capability,
                tool_status=tool_status,
            )
        parsed = _parse_supplemental(_value(response, "output_text", ""))
        if parsed is None:
            return _fallback(
                action_plan, "supplemental_rejected", file_capability=file_capability,
                tool_status=tool_status,
            )
        if any(_value(item, "status") != "completed" for item in output if is_web_search_call(item) or is_file_search_call(item)):
            return _fallback(
                action_plan, "hosted_tool_failed", file_capability=file_capability,
                tool_status=tool_status,
            )
        claims = parsed["claims"]
        scope = secrets.token_hex(12)
        web = admit_web_citations(_value(response, "output_text", ""), claims, output, scope)
        files = admit_file_citations(_value(response, "output_text", ""), claims, output, scope, inventory) if file_offered else []
        if web is None or files is None:
            return _fallback(
                action_plan, "citation_rejected", file_capability=file_capability,
                tool_status=tool_status,
            )
        if not _all_claim_sources_bound(claims, web, files):
            return _fallback(
                action_plan, "citation_rejected", file_capability=file_capability,
                tool_status=tool_status,
            )
        tools_used = _tools_used(output)
        return {
            "schema_version": PUBLIC_SCHEMA,
            "text": _render(action_plan, claims), "action_plan": action_plan, "supplemental_claims": claims,
            "citations": [*web, *files], "tools_used": tools_used, "response_scope": scope,
            "function_status": "completed", "supplemental_status": "completed", "citation_status": "accepted",
            "tool_status": tool_status,
            "file_status_reason": file_capability.reason,
            "degraded": not file_capability.offered, "fallback": None,
        }



def _parse_function_arguments(value: Any) -> dict:
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_FUNCTION_ARGUMENT_BYTES:
        raise ValueError("invalid function arguments")

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
        parsed: dict[str, Any] = {}
        for key, item in pairs:
            if key in parsed:
                raise ValueError("duplicate function argument")
            parsed[key] = item
        return parsed

    parsed = json.loads(value, object_pairs_hook=no_duplicates)
    if not isinstance(parsed, dict):
        raise ValueError("function arguments must be an object")
    return parsed


def _valid_phase_two_output(output: Any, file_offered: bool, output_text: Any = None) -> bool:
    if not isinstance(output, list) or not output or len(output) > MAX_RESPONSE_OUTPUT_ITEMS:
        return False
    messages = 0
    for item in output:
        kind = _value(item, "type")
        if kind not in {"message", "web_search_call", "file_search_call"}:
            return False
        if kind == "file_search_call" and not file_offered:
            return False
        if kind == "message":
            if _value(item, "status") != "completed" or not _message_carries_json(item, output_text):
                return False
            messages += 1
    return messages == 1


def _message_carries_json(item: Any, output_text: Any) -> bool:
    content = _value(item, "content")
    if not isinstance(output_text, str) or not output_text or not isinstance(content, list) or len(content) != 1:
        return False
    part = content[0]
    if not isinstance(part, Mapping) and not hasattr(part, "type"):
        return False
    annotations = _value(part, "annotations", [])
    return (
        _value(part, "type") == "output_text"
        and _value(part, "text") == output_text
        and isinstance(annotations, list)
        and len(annotations) <= MAX_OUTPUT_TEXT_ANNOTATIONS
        and all(_valid_output_annotation(annotation, output_text) for annotation in annotations)
        and (
            not isinstance(part, Mapping)
            or set(part) in ({"type", "text"}, {"type", "text", "annotations"})
        )
    )


def _valid_output_annotation(annotation: Any, output_text: str) -> bool:
    if not isinstance(annotation, Mapping) and not hasattr(annotation, "type"):
        return False
    kind = _value(annotation, "type")
    if kind == "url_citation":
        if isinstance(annotation, Mapping) and set(annotation) != {
            "type", "url", "title", "start_index", "end_index"
        }:
            return False
        url, title = _value(annotation, "url"), _value(annotation, "title")
        start, end = _value(annotation, "start_index"), _value(annotation, "end_index")
        return (
            _bounded_annotation_string(url, MAX_ANNOTATION_URL_BYTES)
            and _bounded_annotation_string(title, MAX_ANNOTATION_TITLE_BYTES)
            and type(start) is int and type(end) is int
            and 0 <= start < end <= len(output_text)
        )
    if kind == "file_citation":
        if isinstance(annotation, Mapping) and set(annotation) not in (
            {"type", "file_id", "filename"},
            {"type", "file_id", "filename", "index"},
        ):
            return False
        index = _value(annotation, "index", None)
        return (
            _bounded_annotation_string(_value(annotation, "file_id"), MAX_ANNOTATION_FILE_BYTES)
            and _bounded_annotation_string(_value(annotation, "filename"), MAX_ANNOTATION_FILE_BYTES)
            and (index is None or (type(index) is int and index >= 0))
        )
    return False


def _bounded_annotation_string(value: Any, maximum_bytes: int) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return len(value.encode("utf-8")) <= maximum_bytes
    except UnicodeEncodeError:
        return False


def _utf8_bytes(value: str) -> int | None:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _parse_supplemental(text: Any) -> dict | None:
    text_bytes = _utf8_bytes(text) if isinstance(text, str) else None
    if text_bytes is None or text_bytes > 16 * 1024:
        return None

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=no_duplicates)
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or set(value) != {"schema_version", "claims"} or value["schema_version"] != SUPPLEMENTAL_SCHEMA or not isinstance(value["claims"], list) or len(value["claims"]) > 5:
        return None
    for claim in value["claims"]:
        if not isinstance(claim, dict) or set(claim) != {"text", "source_scope", "file_refs"}:
            return None
        source_scope = claim["source_scope"]
        file_refs = claim["file_refs"]
        claim_bytes = _utf8_bytes(claim["text"]) if isinstance(claim["text"], str) else None
        if (
            claim_bytes is None
            or claim_bytes == 0
            or claim_bytes > 600
            or not isinstance(source_scope, str)
            or _utf8_bytes(source_scope) is None
            or source_scope not in {"web", "file", "mixed"}
            or not isinstance(file_refs, list)
            or len(file_refs) > 3
            or any(type(reference) is not int or reference < 0 for reference in file_refs)
            or len(file_refs) != len(set(file_refs))
        ):
            return None
        if source_scope == "web" and file_refs:
            return None
        if source_scope in {"file", "mixed"} and not file_refs:
            return None
    return value


def _all_claim_sources_bound(claims: list[dict], web: list[dict], files: list[dict]) -> bool:
    web_claims = {item["claim_ordinal"] for item in web}
    file_claims = {item["claim_ordinal"] for item in files}
    for ordinal, claim in enumerate(claims):
        scope = claim["source_scope"]
        if scope in {"web", "mixed"} and ordinal not in web_claims:
            return False
        if scope in {"file", "mixed"} and ordinal not in file_claims:
            return False
    return True


_FALLBACK_STATUSES = {
    "disabled": ("rejected", "discarded", "not_called"),
    "provider_contract_unavailable": ("rejected", "discarded", "not_called"),
    "preflight_readiness_timeout": ("rejected", "discarded", "not_called"),
    "deadline_exhausted": ("completed", "discarded", "not_called"),
    "function_request_failed": ("rejected", "discarded", "not_called"),
    "function_rejected": ("rejected", "discarded", "not_called"),
    "phase_two_input_limit": ("completed", "discarded", "not_called"),
    "hosted_request_failed": ("completed", "discarded", "rejected"),
    "response_shape_drift": ("completed", "discarded", "rejected"),
    "supplemental_rejected": ("completed", "discarded", "rejected"),
    "hosted_tool_failed": ("completed", "discarded", "rejected"),
    "citation_rejected": ("completed", "discarded", "rejected"),
}


def _fallback(
    action_plan: dict | None, reason: str, *, file_capability: FileCapability | None = None,
    tool_status: dict[str, str] | None = None,
) -> dict:
    statuses = _FALLBACK_STATUSES.get(reason)
    if statuses is None:
        raise ValueError("unknown fallback reason")
    function_status, supplemental_status, citation_status = statuses
    file_status = file_capability.status if file_capability is not None else "not_configured"
    if tool_status is None:
        tool_status = {
            "web": "not_called",
            "file": "not_called" if file_capability and file_capability.offered else file_status,
        }
    return {
        "schema_version": PUBLIC_SCHEMA,
        "text": _render(action_plan, []), "action_plan": action_plan, "supplemental_claims": [], "citations": [], "tools_used": [],
        "response_scope": None, "function_status": function_status, "supplemental_status": supplemental_status,
        "citation_status": citation_status,
        "tool_status": tool_status, "degraded": True, "fallback": reason,
        "file_status_reason": file_capability.reason if file_capability is not None else "not_configured",
    }


def _render(action_plan: dict | None, claims: list[dict]) -> str:
    if action_plan is None:
        return "추가 조사를 사용할 수 없습니다. 의심스러운 메시지의 링크·연락처를 사용하지 말고 공식 채널로 확인하세요."
    actions = "\n".join(f"{item['priority']}. {item['text']}" for item in action_plan["do_now"])
    extra = "\n".join(item["text"] for item in claims)
    return actions if not extra else f"{actions}\n\n추가 조사:\n{extra}"


def _build_messages(snapshot: dict, history: list[dict], question: str) -> list[dict]:
    messages = [{"role": "user", "content": "분석 결과 스냅샷\n" + json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    return messages


def _sanitize_history(history: list[dict]) -> list[dict]:
    if not isinstance(history, list):
        return []
    retained: list[dict] = []
    total_chars = 0
    total_bytes = 0
    for item in reversed(history):
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            return []
        role = item["role"]
        content = item["content"]
        if role not in {"user", "assistant"} or not isinstance(content, str):
            return []
        content = content.strip()
        content_bytes = len(content.encode("utf-8"))
        if not content or len(content) > 2000 or content_bytes > 6 * 1024:
            return []
        if (
            len(retained) >= MAX_CHAT_HISTORY_MESSAGES
            or total_chars + len(content) > MAX_CHAT_HISTORY_CHARS
            or total_bytes + content_bytes > MAX_CHAT_HISTORY_BYTES
        ):
            break
        retained.append({"role": role, "content": content})
        total_chars += len(content)
        total_bytes += content_bytes
    retained.reverse()
    return retained


def _validate_question(question: Any) -> str:
    if not isinstance(question, str) or not (value := question.strip()):
        raise ValueError("질문을 입력해 주세요.")
    if len(value) > MAX_CHAT_QUESTION_CHARS or len(value.encode()) > 12 * 1024:
        raise ValueError("질문은 안전한 최대 길이를 초과했습니다.")
    return value


def _default_file_inventory_provider(
    client: Any, vector_store_id: str, model: str
) -> Callable[[], Mapping[str, Any]]:
    """Build a lazy Vector checker only from a verified offline deployment record."""
    sdk_version = getattr(openai, "__version__", None)
    provider_digest = os.getenv("OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256", "").strip()
    if not isinstance(sdk_version, str) or not sdk_version:
        return _default_file_inventory
    return build_attested_file_inventory_provider(
        client,
        vector_store_id=vector_store_id,
        model=model,
        sdk_version=sdk_version,
        provider_attestation_digest=provider_digest,
    )

def _default_file_inventory() -> Mapping[str, Any] | None:
    """Default offline seam for a strict runtime Vector inventory reader."""
    return None


def _bounded_readiness(operation: Callable[[], bool], timeout: float) -> bool | None:
    """Run a readiness check without accumulating stalled daemon workers."""
    if not _READINESS_SINGLE_FLIGHT.acquire(blocking=False):
        return None
    done = threading.Event()
    result: list[bool] = [False]

    def run() -> None:
        try:
            result[0] = operation() is True
        except Exception:
            result[0] = False
        finally:
            done.set()
            _READINESS_SINGLE_FLIGHT.release()

    threading.Thread(target=run, daemon=True).start()
    return result[0] if done.wait(timeout) else None


def _observed_tool_status(output: Any, file_capability: FileCapability) -> dict[str, str]:
    if not isinstance(output, list):
        return {"web": "not_called", "file": file_capability.status}
    return {
        "web": _tool_status(output, is_web_search_call),
        "file": (
            _tool_status(output, is_file_search_call)
            if file_capability.offered else file_capability.status
        ),
    }

def _default_provider_ready(model: str) -> bool:
    """Verify the deployment-controlled active attestation without provider I/O."""
    path = os.getenv("OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH", "").strip()
    protected_digest = os.getenv("OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256", "").strip()
    sdk_version = getattr(openai, "__version__", None)
    if not path or not protected_digest or not isinstance(sdk_version, str) or not sdk_version:
        return False
    try:
        attestation_health(
            path,
            protected_digest,
            expected_sdk_version=sdk_version,
            expected_model=model,
        )
    except (AttestationError, OSError, ValueError, TypeError):
        return False
    return True

def _risk_level(snapshot: Mapping[str, Any]) -> str:
    value = snapshot.get("overall_risk")
    level = value.get("level") if isinstance(value, Mapping) else None
    return level if level in {"low", "medium", "high", "unknown"} else "unknown"
def _telemetry_vector_state(inventory: Mapping[str, Any] | None, vector_store_id: str | None) -> str:
    if vector_store_id is None:
        return "not_configured"
    return "ready" if _inventory_ready(inventory) else "unavailable"


def _telemetry_corpus_version(inventory: Mapping[str, Any] | None) -> str:
    value = inventory.get("corpus_version") if isinstance(inventory, Mapping) else None
    return corpus_version(value)
def _telemetry_token_count(response: Any) -> int:
    usage = _value(response, "usage")
    total = _value(usage, "total_tokens")
    if type(total) is int and total >= 0:
        return min(total, MAX_TOKEN_COUNT)
    input_tokens = _value(usage, "input_tokens", 0)
    output_tokens = _value(usage, "output_tokens", 0)
    if type(input_tokens) is int and type(output_tokens) is int and input_tokens >= 0 and output_tokens >= 0:
        return min(input_tokens + output_tokens, MAX_TOKEN_COUNT)
    return 0




def _inventory_ready(inventory: Mapping[str, Any] | None) -> bool:
    return isinstance(inventory, Mapping) and inventory.get("ready") is True and inventory.get("fresh") is True and isinstance(inventory.get("files"), list) and bool(inventory["files"])
def _file_capability(
    inventory: Mapping[str, Any] | None, vector_store_id: str | None, readiness_reason: str | None
) -> FileCapability:
    if vector_store_id is None:
        return FileCapability("not_configured", "not_configured")
    if readiness_reason is not None:
        return FileCapability("unavailable", readiness_reason)
    if not isinstance(inventory, Mapping):
        return FileCapability("unavailable", "inventory_unavailable")
    if inventory.get("ready") is not True:
        return FileCapability("unavailable", "inventory_not_ready")
    if inventory.get("fresh") is not True:
        return FileCapability("unavailable", "inventory_stale")
    if not isinstance(inventory.get("files"), list) or not inventory["files"]:
        return FileCapability("unavailable", "inventory_empty")
    return FileCapability("ready", "ready")


def _validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    nodes = 0

    def visit(value: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_ANALYSIS_SNAPSHOT_NODES or depth > MAX_ANALYSIS_SNAPSHOT_DEPTH:
            raise ValueError("analysis snapshot exceeds structural limits")
        if value is None or type(value) in {bool, int, float, str}:
            return
        if isinstance(value, list):
            if len(value) > MAX_ANALYSIS_SNAPSHOT_LIST_ITEMS:
                raise ValueError("analysis snapshot list exceeds item limit")
            for item in value:
                visit(item, depth + 1)
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("analysis snapshot keys must be strings")
                visit(item, depth + 1)
            return
        raise ValueError("analysis snapshot contains an unsupported value")

    visit(snapshot, 0)
    if _json_bytes(snapshot) > MAX_ANALYSIS_SNAPSHOT_BYTES:
        raise ValueError("analysis snapshot exceeds byte limit")


def _tools_used(output: list[Any]) -> list[str]:
    result = []
    if any(is_web_search_call(item) for item in output): result.append("web_search")
    if any(is_file_search_call(item) for item in output): result.append("file_search")
    return result


def _tool_status(output: list[Any], predicate: Callable[[Any], bool]) -> str:
    calls = [item for item in output if predicate(item)]
    if not calls: return "unselected"
    if any(_value(item, "status") != "completed" for item in calls): return "failed"
    return "completed"


def _enabled_from_env() -> bool:
    return is_openai_followup_enabled()


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _value(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)
