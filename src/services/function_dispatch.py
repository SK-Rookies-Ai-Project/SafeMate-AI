"""Strict host-side dispatcher for the SafeMate local-analysis function."""

from __future__ import annotations

import json
from typing import Any

from src.client_factory import get_analysis_client


LOCAL_ANALYSIS_FUNCTION_NAME = "run_local_security_analysis"


def build_local_analysis_function_tool() -> dict:
    """Return the only custom function exposed by the SafeMate agent."""
    return {
        "type": "function",
        "name": LOCAL_ANALYSIS_FUNCTION_NAME,
        "description": "SafeMate 로컬 모델로 현재 검증된 입력을 분석합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "analysis_scope": {"type": "string", "enum": ["full"]},
            },
            "required": ["analysis_scope"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def validate_local_analysis_function_call(call: Any) -> None:
    """Reject calls that do not exactly match the advertised strict contract."""
    if _get_value(call, "type") != "function_call":
        raise ValueError("Function call output item is required.")
    if _get_value(call, "name") != LOCAL_ANALYSIS_FUNCTION_NAME:
        raise ValueError("Unknown function call.")
    call_id = _get_value(call, "call_id")
    if not isinstance(call_id, str) or not call_id:
        raise ValueError("Function call ID is required.")

    arguments = _get_value(call, "arguments")
    if not isinstance(arguments, str):
        raise ValueError("Function arguments must be JSON text.")
    try:
        parsed_arguments = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ValueError("Function arguments are not valid JSON.") from exc
    if parsed_arguments != {"analysis_scope": "full"}:
        raise ValueError("Function arguments do not match the strict contract.")


def dispatch_local_analysis_function(
    call: Any,
    *,
    validated_request: dict,
    analysis_client: Any | None = None,
) -> tuple[dict, dict]:
    """Execute the local model with the host-retained request, never model input."""
    validate_local_analysis_function_call(call)
    client = analysis_client or get_analysis_client()
    result = client.analyze(validated_request)
    if not isinstance(result, dict):
        raise TypeError("Local analysis must return a dictionary.")
    return result, {
        "type": "function_call_output",
        "call_id": _get_value(call, "call_id"),
        "output": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
    }


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
