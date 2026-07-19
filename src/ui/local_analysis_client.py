"""Local adapter that combines message and URL model results."""

from __future__ import annotations

import json
from typing import Any, Optional, Union
from pathlib import Path

from src.analyzers import url_analyzer
from src.analyzers.text_analyzer import analyze_message
from src.config import MAX_URLS_TO_ANALYZE
from src.pipeline import calculate_overall_risk
from src.ui.url_candidates import deduplicate_and_prioritize


class LocalAnalysisClient:
    """Build AnalysisResponse-compatible results from local model outputs."""

    def __init__(
        self,
        *,
        url_model_path: Optional[Union[str, Path]] = None,
        url_model_kind: str = "char",
    ) -> None:
        self.url_model_path = url_model_path
        self.url_model_kind = url_model_kind

    def analyze(self, payload: dict) -> dict:
        candidates = payload.get("url_candidates", [])
        unique_candidates = deduplicate_and_prioritize(candidates)
        selected = unique_candidates[:MAX_URLS_TO_ANALYZE]
        message_analysis = analyze_message(
            payload["body"],
            payload["input_type"],
            subject=payload.get("subject"),
        )
        url_analysis = [self._analyze_candidate(candidate) for candidate in selected]
        failed_count = sum(1 for item in url_analysis if item.get("status") != "success")
        message_succeeded = message_analysis.get("status") == "success"
        url_succeeded = any(item.get("status") == "success" for item in url_analysis)

        response = {
            "schema_version": "1.0",
            "request_id": payload["request_id"],
            "input_type": payload.get("input_type", "sms"),
            "status": "success" if message_succeeded or url_succeeded else "error",
            "overall_risk": calculate_overall_risk(message_analysis, url_analysis),
            "summary": _build_summary(message_analysis, url_analysis),
            "risk_reasons": _build_risk_reasons(message_analysis, url_analysis),
            "recommended_actions": _recommended_actions(message_analysis, url_analysis),
            "message_analysis": message_analysis,
            "url_analysis_summary": {
                "candidate_count": len(unique_candidates),
                "analyzed_count": len(selected),
                "omitted_url_count": max(0, len(unique_candidates) - len(selected)),
                "failed_count": failed_count,
            },
            "url_analysis": url_analysis,
            "web_evidence": [],
            "file_evidence": [],
            "limitations": [],
            "errors": _build_errors(message_analysis, url_analysis),
        }
        return _json_safe(response)

    def _analyze_candidate(self, candidate: dict) -> dict:
        result = url_analyzer.analyze_url(
            candidate["url"],
            model_path=self.url_model_path,
            model_kind=self.url_model_kind,
        )
        merged = {
            **result,
            "input_indexes": candidate["input_indexes"],
            "occurrence_count": candidate["occurrence_count"],
            "source_types": candidate["source_types"],
            "displayed_url": candidate.get("displayed_url"),
            "displayed_domain": candidate.get("displayed_domain"),
            "destination_domain": candidate.get("destination_domain"),
            "display_href_mismatch": candidate.get(
                "display_href_mismatch", False
            ),
        }
        candidate_signals = candidate.get("signals", [])
        model_signals = result.get("signals", [])
        merged["signals"] = list(dict.fromkeys(candidate_signals + model_signals))
        return merged


def _build_summary(message_analysis: dict, url_analysis: list[dict]) -> str:
    parts: list[str] = []
    if message_analysis.get("status") == "success":
        label = message_analysis.get("label", "unknown")
        parts.append(f"Message analysis classified the content as {label}.")
    else:
        parts.append("Message analysis could not be completed.")

    successful_urls = [item for item in url_analysis if item.get("status") == "success"]
    risky_urls = [
        item for item in successful_urls if item.get("label") in {"suspicious", "malicious"}
    ]
    if risky_urls:
        parts.append(f"URL analysis found {len(risky_urls)} risky URL candidate(s).")
    elif successful_urls:
        parts.append("URL analysis did not find high-risk URL candidates.")
    elif url_analysis:
        parts.append("URL analysis could not be completed.")
    return " ".join(parts)


def _build_risk_reasons(message_analysis: dict, url_analysis: list[dict]) -> list[str]:
    reasons: list[str] = []
    if message_analysis.get("status") == "success":
        probability = message_analysis.get("phishing_probability")
        label = message_analysis.get("label", "unknown")
        if isinstance(probability, (int, float)) and not isinstance(probability, bool):
            reasons.append(
                f"Message content was classified as {label} with a {probability:.0%} phishing probability."
            )
        reasons.extend(str(signal) for signal in message_analysis.get("signals", [])[:3])
    else:
        reasons.append("Message model inference failed; URL results remain available.")

    for item in url_analysis:
        if item.get("display_href_mismatch"):
            reasons.append("Displayed link text and actual destination domain do not match.")
        if item.get("status") != "success":
            reasons.append(f"URL analysis failed for {item.get('url', 'unknown URL')}.")
            continue
        score = item.get("risk_score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            reasons.append(
                f"{item.get('url', 'URL')} was classified as {item.get('label', 'unknown')} with a {score:.0%} risk score."
            )
    return list(dict.fromkeys(reasons))[:5]


def _recommended_actions(message_analysis: dict, url_analysis: list[dict]) -> list[str]:
    actions = [
        "Do not open suspicious links directly from the message or email.",
        "Verify the request through the organization's official website or app.",
    ]
    if message_analysis.get("status") != "success" or any(
        item.get("status") != "success" for item in url_analysis
    ):
        actions.append("Retry the failed analysis before relying on its result.")
    return actions


def _build_errors(message_analysis: dict, url_analysis: list[dict]) -> list[dict]:
    errors: list[dict] = []
    if message_analysis.get("status") != "success":
        error = message_analysis.get("error")
        if isinstance(error, dict):
            errors.append(
                {
                    "component": "message_analysis",
                    "code": "MESSAGE_MODEL_FAILED",
                    "message": error.get("message") or "Message analysis failed",
                    "retryable": bool(error.get("retryable", False)),
                }
            )
        else:
            errors.append(
                {
                    "component": "message_analysis",
                    "code": "MESSAGE_MODEL_FAILED",
                    "message": "Message analysis failed",
                    "retryable": False,
                }
            )

    for item in url_analysis:
        if item.get("status") != "success":
            errors.append(
                {
                    "code": "URL_MODEL_FAILED",
                    "message": item.get("error") or "URL analysis failed",
                    "url": item.get("url"),
                }
            )
    return errors


def _json_safe(value: Any) -> Any:
    """Normalize model outputs to values accepted by JSON encoders."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def _json_default(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        normalized = item()
        if normalized is None or isinstance(
            normalized, (str, int, float, bool)
        ):
            return normalized
    raise TypeError(f"Unsupported model output type: {type(value).__name__}")
