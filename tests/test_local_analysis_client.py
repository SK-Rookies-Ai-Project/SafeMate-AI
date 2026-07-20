import json
from unittest.mock import patch

import numpy as np
import pytest

from src.ui.local_analysis_client import LocalAnalysisClient, _json_safe


def test_local_client_integrates_sms_and_url_analysis():
    request = {
        "schema_version": "1.0",
        "request_id": "analysis-local",
        "input_type": "sms",
        "body": "Verify your account at https://evil.example/login",
        "url_candidates": [
            {
                "url": "https://evil.example/login",
                "source_type": "text",
                "input_index": 0,
            }
        ],
    }
    message_result = {
        "status": "success",
        "label": "phishing",
        "phishing_probability": 0.86,
        "signals": ["Urgent account verification request"],
        "top_features": [],
        "model_version": "sms-v1",
        "error": None,
    }
    url_result = {
        "status": "success",
        "url": "https://evil.example/login",
        "label": "malicious",
        "risk_score": 0.91,
        "signals": ["Known risky domain"],
        "features": [],
        "model_version": "url-v1",
        "error": None,
    }

    with patch(
        "src.ui.local_analysis_client.analyze_message", return_value=message_result
    ) as analyze_message, patch(
        "src.ui.local_analysis_client.url_analyzer.analyze_url", return_value=url_result
    ) as analyze_url:
        result = LocalAnalysisClient().analyze(request)

    analyze_message.assert_called_once_with(
        request["body"], "sms", subject=None
    )
    analyze_url.assert_called_once_with(
        "https://evil.example/login", model_path=None, model_kind="char"
    )
    assert result["status"] == "success"
    assert result["message_analysis"] == message_result
    assert result["overall_risk"] == {"score": 0.91, "level": "high"}
    assert result["url_analysis_summary"] == {
        "candidate_count": 1,
        "analyzed_count": 1,
        "omitted_url_count": 0,
        "failed_count": 0,
    }
    assert not any(
        item.get("code") == "MESSAGE_MODEL_NOT_RUN"
        for item in result["limitations"]
    )
    json.dumps(result)


def test_local_client_surfaces_structured_message_failure_with_url_result():
    request = {
        "schema_version": "1.0",
        "request_id": "analysis-message-failure",
        "input_type": "sms",
        "body": "Please check https://safe.example/notice",
        "url_candidates": [
            {
                "url": "https://safe.example/notice",
                "source_type": "text",
                "input_index": 0,
            }
        ],
    }
    message_result = {
        "status": "error",
        "label": "unknown",
        "phishing_probability": None,
        "signals": [],
        "top_features": [],
        "model_version": "sms-v1",
        "error": {
            "code": "MODEL_NOT_AVAILABLE",
            "message": "SMS model is unavailable.",
            "retryable": False,
        },
    }
    url_result = {
        "status": "success",
        "url": "https://safe.example/notice",
        "label": "normal",
        "risk_score": 0.08,
        "signals": [],
        "features": [],
        "model_version": "url-v1",
        "error": None,
    }

    with patch(
        "src.ui.local_analysis_client.analyze_message", return_value=message_result
    ), patch(
        "src.ui.local_analysis_client.url_analyzer.analyze_url", return_value=url_result
    ):
        result = LocalAnalysisClient().analyze(request)

    assert result["status"] == "success"
    assert result["message_analysis"] == message_result
    assert result["errors"] == [
        {
            "component": "message_analysis",
            "code": "MESSAGE_MODEL_FAILED",
            "message": "SMS model is unavailable.",
            "retryable": False,
        }
    ]
    assert result["url_analysis_summary"]["failed_count"] == 0
    assert result["overall_risk"] == {"score": 0.08, "level": "low"}
    json.dumps(result)


def test_json_safe_converts_numpy_scalars_without_stringifying_them():
    assert _json_safe({"score": np.float64(0.75), "count": np.int64(2)}) == {
        "score": 0.75,
        "count": 2,
    }


def test_json_safe_rejects_arbitrary_unknown_objects():
    with pytest.raises(TypeError):
        _json_safe({"value": object()})
