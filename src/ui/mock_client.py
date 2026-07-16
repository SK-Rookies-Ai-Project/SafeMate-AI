"""Mock analysis client used while API and model integration is in progress."""

from __future__ import annotations

import json
from typing import Protocol
from urllib.parse import urlsplit

from src.config import (
    MAX_ANALYSIS_REQUEST_BYTES,
    MAX_URL_CANDIDATES,
    MAX_URLS_TO_ANALYZE,
)
from src.pipeline import calculate_overall_risk


SOURCE_PRIORITY = {"text": 0, "href": 1, "image_src": 2}


class AnalysisRequestValidationError(ValueError):
    """Raised before oversized analysis payloads reach a model or API."""


class AnalysisClient(Protocol):
    def analyze(self, payload: dict) -> dict:
        """Return an AnalysisResponse-compatible dictionary."""


class MockAnalysisClient:
    """Return deterministic UI-development data without external calls."""

    def analyze(self, payload: dict) -> dict:
        candidates = payload.get("url_candidates", [])
        unique_candidates = _deduplicate_and_prioritize(candidates)
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


def _deduplicate_and_prioritize(candidates: list[dict]) -> list[dict]:
    """Merge duplicate URLs, then order by source priority and first appearance."""
    grouped: dict[str, dict] = {}
    for position, candidate in enumerate(candidates):
        url = candidate.get("url")
        source_type = candidate.get("source_type")
        input_index = candidate.get("input_index")
        if not isinstance(url, str) or not url.strip():
            continue
        if source_type not in SOURCE_PRIORITY or not isinstance(input_index, int):
            continue

        normalized_url = url.strip()
        group = grouped.setdefault(
            normalized_url,
            {
                "url": normalized_url,
                "input_indexes": [],
                "source_types": [],
                "first_position": position,
                "priority": SOURCE_PRIORITY[source_type],
                "signals": [],
                "displayed_url": candidate.get("displayed_url"),
                "displayed_domain": candidate.get("displayed_domain"),
                "destination_domain": candidate.get("destination_domain"),
                "display_href_mismatch": bool(
                    candidate.get("display_href_mismatch", False)
                ),
            },
        )
        group["input_indexes"].append(input_index)
        if source_type not in group["source_types"]:
            group["source_types"].append(source_type)
        group["priority"] = min(group["priority"], SOURCE_PRIORITY[source_type])
        for signal in candidate.get("signals", []):
            if signal not in group["signals"]:
                group["signals"].append(signal)
        if candidate.get("display_href_mismatch"):
            group["display_href_mismatch"] = True
            for field in ("displayed_url", "displayed_domain", "destination_domain"):
                if candidate.get(field):
                    group[field] = candidate[field]

    ordered = sorted(
        grouped.values(),
        key=lambda item: (item["priority"], item["first_position"]),
    )
    for item in ordered:
        item["input_indexes"].sort()
        item["source_types"].sort(key=SOURCE_PRIORITY.__getitem__)
        item["occurrence_count"] = len(item["input_indexes"])
        item.pop("first_position")
        item.pop("priority")
    return ordered


def build_analysis_request(prepared_input: dict, request_id: str) -> dict:
    """Build a bounded JSON-compatible analysis request."""
    request = {
        "schema_version": "1.0",
        "request_id": request_id,
        "input_type": prepared_input["input_type"],
        "subject": prepared_input.get("subject"),
        "body": prepared_input["body"],
        "url_candidates": prepared_input.get("url_candidates", [])[
            :MAX_URL_CANDIDATES
        ],
    }
    request_size = len(
        json.dumps(
            request,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if request_size > MAX_ANALYSIS_REQUEST_BYTES:
        raise AnalysisRequestValidationError(
            "분석 요청 크기가 허용된 최대 크기를 초과했습니다."
        )
    return request
