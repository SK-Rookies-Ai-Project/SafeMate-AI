"""Content-free, best-effort telemetry for the follow-up boundary."""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable, Mapping
from typing import Any

SCHEMA_VERSION = "safemate.followup.telemetry.v1"
MAX_DURATION_MS = 120_000
MAX_TOKEN_COUNT = 12_000
MAX_TOOL_COUNT = 5
MAX_RESULT_COUNT = 16
MAX_CLAIM_COUNT = 5

_EVENT_FIELDS = frozenset({
    "schema_version", "host_turn_ref", "phase", "attempt", "tool", "state", "reason",
    "duration_ms", "model_alias", "token_count", "tool_count", "result_count", "claim_count",
    "fallback", "vector_state", "corpus_version",
})
_PHASES = frozenset({"preflight", "phase_one", "function", "phase_two", "citation", "fallback"})
_TOOLS = frozenset({"none", "function", "web_search", "file_search", "hosted"})
_STATES = frozenset({"started", "skipped", "completed", "rejected", "failed", "accepted", "fallback"})
_REASONS = frozenset({
    "none", "disabled", "function_request_failed", "function_rejected", "phase_two_input_limit",
    "provider_contract_unavailable", "preflight_readiness_timeout",
    "deadline_exhausted", "hosted_request_failed", "response_shape_drift",
    "supplemental_rejected", "hosted_tool_failed", "citation_rejected", "completed",
})
_FALLBACKS = frozenset({"none"}) | (_REASONS - {"none", "completed"})
_VECTOR_STATES = frozenset({"not_checked", "not_configured", "unavailable", "ready"})
_MODEL_ALIASES = {"gpt-5.6": "gpt-5.6", "gpt-5.4": "gpt-5.4", "gpt-4.1": "gpt-4.1", "gpt-test": "test"}
_HEX_REF = re.compile(r"^[0-9a-f]{64}$")
_CORPUS_VERSION = re.compile(r"^(?:unknown|[0-9]{4}-[0-9]{2}(?:\.[0-9]+){0,2})$")
_TRANSITIONS = frozenset({
    ("preflight", "fallback", "disabled", "disabled", "none"),
    ("preflight", "fallback", "provider_contract_unavailable", "provider_contract_unavailable", "none"),
    ("preflight", "fallback", "preflight_readiness_timeout", "preflight_readiness_timeout", "none"),
    ("phase_one", "started", "none", "none", "function"),
    ("phase_one", "fallback", "function_request_failed", "function_request_failed", "function"),
    ("function", "completed", "completed", "none", "function"),
    ("function", "fallback", "function_rejected", "function_rejected", "function"),
    ("phase_two", "started", "none", "none", "hosted"),
    ("phase_two", "fallback", "phase_two_input_limit", "phase_two_input_limit", "none"),
    ("phase_two", "fallback", "deadline_exhausted", "deadline_exhausted", "none"),
    ("phase_two", "fallback", "deadline_exhausted", "deadline_exhausted", "hosted"),
    ("phase_two", "fallback", "hosted_request_failed", "hosted_request_failed", "hosted"),
    ("phase_two", "fallback", "response_shape_drift", "response_shape_drift", "hosted"),
    ("phase_two", "fallback", "supplemental_rejected", "supplemental_rejected", "hosted"),
    ("phase_two", "fallback", "hosted_tool_failed", "hosted_tool_failed", "hosted"),
    ("citation", "accepted", "completed", "none", "hosted"),
    ("citation", "fallback", "citation_rejected", "citation_rejected", "hosted"),
})

TelemetrySink = Callable[[Mapping[str, Any]], None]


def new_host_turn_seed() -> bytes:
    """Return entropy which is independent of all provider and host identifiers."""
    return secrets.token_bytes(32)


def host_turn_reference(seed: bytes) -> str:
    """Create a framed, one-way reference without retaining the seed in an event."""
    if not isinstance(seed, bytes) or len(seed) < 16:
        raise ValueError("host turn seed must contain at least 128 bits")
    return hashlib.sha256(b"safemate.followup.host-turn.v1\x00" + seed).hexdigest()


def model_alias(model: object) -> str:
    """Map deployment model names to the closed allowlist without recording input."""
    return _MODEL_ALIASES.get(model, "unallowlisted") if isinstance(model, str) else "unallowlisted"

def corpus_version(value: object) -> str:
    """Return a bounded corpus release label or the content-free unknown marker."""
    return value if isinstance(value, str) and _CORPUS_VERSION.fullmatch(value) else "unknown"



def validate_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return a copied valid event, or drop any non-canonical/unsafe payload."""
    if not isinstance(event, Mapping) or set(event) != _EVENT_FIELDS:
        return None
    value = dict(event)
    if value["schema_version"] != SCHEMA_VERSION or not _valid_string(value["host_turn_ref"], _HEX_REF):
        return None
    if not _member(value["phase"], _PHASES) or not _member(value["tool"], _TOOLS) or not _member(value["state"], _STATES):
        return None
    if not _member(value["reason"], _REASONS) or not _member(value["fallback"], _FALLBACKS):
        return None
    if not _member(value["model_alias"], frozenset(_MODEL_ALIASES.values()) | {"unallowlisted"}):
        return None
    if not _member(value["vector_state"], _VECTOR_STATES) or not _valid_string(value["corpus_version"], _CORPUS_VERSION):
        return None
    if type(value["attempt"]) is not int or not 1 <= value["attempt"] <= 2:
        return None
    if value["attempt"] != (2 if value["phase"] == "phase_two" else 1):
        return None
    if (
        value["phase"], value["state"], value["reason"], value["fallback"], value["tool"]
    ) not in _TRANSITIONS:
        return None
    for key, maximum in (("duration_ms", MAX_DURATION_MS), ("token_count", MAX_TOKEN_COUNT),
                         ("tool_count", MAX_TOOL_COUNT), ("result_count", MAX_RESULT_COUNT),
                         ("claim_count", MAX_CLAIM_COUNT)):
        if type(value[key]) is not int or not 0 <= value[key] <= maximum:
            return None
    return value


def _valid_string(value: Any, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and bool(pattern.fullmatch(value))
def _member(value: Any, allowed: frozenset[str]) -> bool:
    return isinstance(value, str) and value in allowed



class FollowupTelemetry:
    """Safely emits independently validated closed-schema events to an optional sink."""

    def __init__(self, sink: TelemetrySink | None = None, *, seed: bytes | None = None) -> None:
        self._sink = sink
        self._host_turn_ref = host_turn_reference(new_host_turn_seed() if seed is None else seed)

    def emit(
        self, *, phase: str, attempt: int = 1, tool: str = "none", state: str,
        reason: str = "none", duration_ms: int = 0, model: object = None,
        token_count: int = 0, tool_count: int = 0, result_count: int = 0,
        claim_count: int = 0, fallback: str = "none", vector_state: str = "not_checked",
        corpus_version: str = "unknown",
    ) -> None:
        event = validate_event({
            "schema_version": SCHEMA_VERSION, "host_turn_ref": self._host_turn_ref,
            "phase": phase, "attempt": attempt, "tool": tool, "state": state, "reason": reason,
            "duration_ms": duration_ms, "model_alias": model_alias(model), "token_count": token_count,
            "tool_count": tool_count, "result_count": result_count, "claim_count": claim_count,
            "fallback": fallback, "vector_state": vector_state, "corpus_version": corpus_version,
        })
        if event is None or self._sink is None:
            return
        try:
            self._sink(event)
        except Exception:
            return
