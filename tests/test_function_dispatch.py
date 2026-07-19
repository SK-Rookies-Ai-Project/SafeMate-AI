import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.services.function_dispatch import (
    LOCAL_ANALYSIS_FUNCTION_NAME,
    build_local_analysis_function_tool,
    dispatch_local_analysis_function,
)


def _function_call(arguments: str = '{"analysis_scope":"full"}'):
    return SimpleNamespace(
        type="function_call",
        name=LOCAL_ANALYSIS_FUNCTION_NAME,
        call_id="call_local_analysis",
        arguments=arguments,
    )


def test_builds_one_strict_local_analysis_function_tool():
    assert build_local_analysis_function_tool() == {
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


def test_dispatches_with_host_retained_request_and_returns_matching_call_output():
    request = {
        "request_id": "analysis-host-retained",
        "input_type": "sms",
        "body": "canonical host input",
        "url_candidates": [],
    }
    result = {
        "request_id": "analysis-host-retained",
        "status": "success",
        "overall_risk": {"level": "high", "score": 0.9},
    }
    analysis_client = Mock()
    analysis_client.analyze.return_value = result

    actual_result, output = dispatch_local_analysis_function(
        _function_call(),
        validated_request=request,
        analysis_client=analysis_client,
    )

    analysis_client.analyze.assert_called_once_with(request)
    assert actual_result is result
    assert output == {
        "type": "function_call_output",
        "call_id": "call_local_analysis",
        "output": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
    }


@pytest.mark.parametrize(
    "call",
    [
        SimpleNamespace(
            type="function_call",
            name="unknown_function",
            call_id="call_unknown",
            arguments='{"analysis_scope":"full"}',
        ),
        _function_call("not-json"),
        _function_call("[]"),
        _function_call("{}"),
        _function_call('{"analysis_scope":"partial"}'),
        _function_call(
            '{"analysis_scope":"full","body":"model-authored replacement"}'
        ),
        SimpleNamespace(
            type="function_call",
            name=LOCAL_ANALYSIS_FUNCTION_NAME,
            call_id="",
            arguments='{"analysis_scope":"full"}',
        ),
    ],
)
def test_rejects_unknown_or_malformed_function_calls(call):
    analysis_client = Mock()

    with pytest.raises(ValueError):
        dispatch_local_analysis_function(
            call,
            validated_request={"body": "canonical host input"},
            analysis_client=analysis_client,
        )

    analysis_client.analyze.assert_not_called()


def test_uses_existing_analysis_client_factory_when_not_injected(monkeypatch):
    request = {"request_id": "analysis-factory", "body": "canonical"}
    result = {"request_id": "analysis-factory", "status": "success"}
    analysis_client = Mock()
    analysis_client.analyze.return_value = result
    factory = Mock(return_value=analysis_client)
    monkeypatch.setattr("src.services.function_dispatch.get_analysis_client", factory)

    actual_result, _ = dispatch_local_analysis_function(
        _function_call(),
        validated_request=request,
    )

    factory.assert_called_once_with()
    analysis_client.analyze.assert_called_once_with(request)
    assert actual_result is result
