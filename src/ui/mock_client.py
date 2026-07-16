"""Mock analysis client used while API and model integration is in progress."""

from __future__ import annotations

from urllib.parse import urlsplit

from src.config import MAX_URLS_TO_ANALYZE
from src.pipeline import calculate_overall_risk
from src.ui.url_candidates import deduplicate_and_prioritize


class MockAnalysisClient:
    """Return deterministic UI-development data without external calls."""

    def analyze(self, payload: dict) -> dict:
        candidates = payload.get("url_candidates", [])
        unique_candidates = deduplicate_and_prioritize(candidates)
        selected = unique_candidates[:MAX_URLS_TO_ANALYZE]
        body = str(payload.get("body", "")).lower()
        suspicious_terms = ("계정", "인증", "비밀번호", "입금", "긴급", "확인")
        matched_terms = [term for term in suspicious_terms if term in body]
        has_risk = bool(selected or matched_terms)
        input_type = payload.get("input_type", "sms")

        risk_reasons = [f"본문에서 '{term}' 표현이 확인되었습니다." for term in matched_terms[:3]]
        if selected:
            risk_reasons.append("외부 URL이 포함되어 별도 확인이 필요합니다.")
        if any(item.get("display_href_mismatch") for item in selected):
            risk_reasons.append("이메일에 표시된 주소와 실제 연결 주소가 다릅니다.")
        if not risk_reasons:
            risk_reasons.append("Mock 분석에서 뚜렷한 위험 신호가 확인되지 않았습니다.")

        url_analysis = [
            {
                "url": candidate["url"],
                "input_indexes": candidate["input_indexes"],
                "occurrence_count": candidate["occurrence_count"],
                "source_types": candidate["source_types"],
                "status": "success",
                "label": "suspicious",
                "risk_score": 0.72,
                "signals": candidate.get("signals", []) + ["Mock URL 분석 결과"],
                "displayed_url": candidate.get("displayed_url"),
                "displayed_domain": candidate.get("displayed_domain"),
                "destination_domain": candidate.get("destination_domain"),
                "display_href_mismatch": candidate.get(
                    "display_href_mismatch", False
                ),
                "features": _build_mock_url_features(candidate["url"]),
                "model_version": "mock-url-v1",
                "error": None,
            }
            for candidate in selected
        ]
        message_analysis = {
            "status": "success",
            "label": "phishing" if has_risk else "normal",
            "phishing_probability": 0.84 if has_risk else 0.12,
            "signals": matched_terms or ["Mock 메시지 분석 결과"],
            "top_features": [
                {
                    "name": term,
                    "value": 1.0,
                    "contribution": round(0.31 - index * 0.04, 2),
                }
                for index, term in enumerate(matched_terms[:5])
            ],
            "model_version": "mock-message-v1",
            "error": None,
        }

        return {
            "schema_version": "1.0",
            "request_id": payload["request_id"],
            "input_type": input_type,
            "status": "success",
            "overall_risk": calculate_overall_risk(message_analysis, url_analysis),
            "summary": (
                "주의가 필요한 표현이나 URL이 확인되었습니다."
                if has_risk
                else "Mock 분석에서 주요 위험 신호가 확인되지 않았습니다."
            ),
            "risk_reasons": risk_reasons,
            "recommended_actions": [
                "메시지 또는 이메일 속 URL을 바로 열지 마세요.",
                "발신 기관의 공식 채널에서 내용을 별도로 확인하세요.",
            ],
            "message_analysis": message_analysis,
            "url_analysis_summary": {
                "candidate_count": len(unique_candidates),
                "analyzed_count": len(selected),
                "omitted_url_count": max(0, len(unique_candidates) - len(selected)),
                "failed_count": 0,
            },
            "url_analysis": url_analysis,
            "web_evidence": [],
            "file_evidence": [],
            "limitations": [
                {
                    "code": "MOCK_RESULT",
                    "message": "현재 화면은 UI 개발용 Mock 분석 결과를 표시합니다.",
                },
                {
                    "code": "MODEL_NOT_DETERMINISTIC",
                    "message": "분석 결과만으로 실제 피싱 여부를 확정할 수 없습니다.",
                },
            ],
            "errors": [],
        }


def _build_mock_url_features(url: str) -> list[dict]:
    """Return deterministic demo features while the URL model is unavailable."""
    try:
        parsed = urlsplit(url if "://" in url else "https://" + url)
        hostname = parsed.hostname or ""
    except ValueError:
        hostname = ""
    special_character_count = sum(not char.isalnum() for char in url)
    subdomain_count = max(0, len(hostname.split(".")) - 2) if hostname else 0
    return [
        {
            "name": "URL 길이",
            "raw_value": len(url),
            "normalized_value": min(len(url) / 120, 1.0),
            "contribution": 0.18,
        },
        {
            "name": "특수문자 개수",
            "raw_value": special_character_count,
            "normalized_value": min(special_character_count / 20, 1.0),
            "contribution": 0.14,
        },
        {
            "name": "서브도메인 개수",
            "raw_value": subdomain_count,
            "normalized_value": min(subdomain_count / 5, 1.0),
            "contribution": 0.11,
        },
    ]

