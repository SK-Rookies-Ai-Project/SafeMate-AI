from unittest.mock import patch

from src.ui.local_url_client import LocalUrlAnalysisClient


def test_local_url_client_runs_url_model_and_preserves_candidate_metadata():
    request = {
        "schema_version": "1.0",
        "request_id": "analysis-local-url",
        "input_type": "email",
        "subject": "test",
        "body": "body",
        "url_candidates": [
            {
                "url": "https://evil.example/login",
                "source_type": "href",
                "input_index": 3,
                "displayed_url": "https://bank.example/login",
                "displayed_domain": "bank.example",
                "destination_domain": "evil.example",
                "display_href_mismatch": True,
                "signals": ["candidate mismatch"],
            },
            {
                "url": "https://evil.example/login",
                "source_type": "text",
                "input_index": 1,
            },
        ],
    }
    model_result = {
        "status": "success",
        "url": "https://evil.example/login",
        "label": "malicious",
        "risk_score": 0.91,
        "signals": ["model signal"],
        "features": [],
        "model_version": "url-v1",
        "error": None,
    }

    with patch(
        "src.ui.local_url_client.url_analyzer.analyze_url",
        return_value=model_result,
    ) as analyze_url:
        result = LocalUrlAnalysisClient(
            model_path="models/url_char_model.joblib"
        ).analyze(request)

    analyze_url.assert_called_once_with(
        "https://evil.example/login",
        model_path="models/url_char_model.joblib",
        model_kind="feature",
    )
    assert result["request_id"] == "analysis-local-url"
    assert result["message_analysis"]["status"] == "skipped"
    assert result["overall_risk"] == {"score": 0.91, "level": "high"}
    assert result["url_analysis_summary"] == {
        "candidate_count": 1,
        "analyzed_count": 1,
        "omitted_url_count": 0,
        "failed_count": 0,
    }

    url_result = result["url_analysis"][0]
    assert url_result["input_indexes"] == [1, 3]
    assert url_result["source_types"] == ["text", "href"]
    assert url_result["occurrence_count"] == 2
    assert url_result["display_href_mismatch"] is True
    assert url_result["signals"] == ["candidate mismatch", "model signal"]
