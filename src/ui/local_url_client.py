"""Local analysis client that runs only the URL model."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from src.analyzers import url_analyzer
from src.config import MAX_URLS_TO_ANALYZE
from src.pipeline import calculate_overall_risk
from src.ui.url_candidates import deduplicate_and_prioritize


class LocalUrlAnalysisClient:
    """Return AnalysisResponse-compatible results using the local URL analyzer."""

    def __init__(
        self,
        *,
        model_path: Optional[Union[str, Path]] = None,
        model_kind: str = "feature",
    ) -> None:
        self.model_path = model_path
        self.model_kind = model_kind

    def analyze(self, payload: dict) -> dict:
        candidates = payload.get("url_candidates", [])
        unique_candidates = deduplicate_and_prioritize(candidates)
        selected = unique_candidates[:MAX_URLS_TO_ANALYZE]

        url_analysis = [self._analyze_candidate(candidate) for candidate in selected]
        message_analysis = _skipped_message_analysis()
        failed_count = sum(1 for item in url_analysis if item.get("status") != "success")

        return {
            "schema_version": "1.0",
            "request_id": payload["request_id"],
            "input_type": payload.get("input_type", "sms"),
            "status": "success" if failed_count < len(selected) else "error",
            "overall_risk": calculate_overall_risk(message_analysis, url_analysis),
            "summary": _build_summary(url_analysis),
            "risk_reasons": _build_risk_reasons(url_analysis),
            "recommended_actions": _recommended_actions(url_analysis),
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
            "limitations": [
                {
                    "code": "MESSAGE_MODEL_NOT_RUN",
                    "message": (
                        "This backend runs only the local URL model; message "
                        "classification is skipped."
                    ),
                }
            ],
            "errors": _build_errors(url_analysis),
        }

    def _analyze_candidate(self, candidate: dict) -> dict:
        result = url_analyzer.analyze_url(
            candidate["url"],
            model_path=self.model_path,
            model_kind=self.model_kind,
        )
        merged = {
            **result,
            "input_indexes": candidate["input_indexes"],
            "occurrence_count": candidate["occurrence_count"],
            "source_types": candidate["source_types"],
            "displayed_url": candidate.get("displayed_url"),
            "displayed_domain": candidate.get("displayed_domain"),
            "destination_domain": candidate.get("destination_domain"),
            "display_href_mismatch": candidate.get("display_href_mismatch", False),
        }
        candidate_signals = candidate.get("signals", [])
        model_signals = result.get("signals", [])
        merged["signals"] = list(dict.fromkeys(candidate_signals + model_signals))
        return merged


def _skipped_message_analysis() -> dict:
    return {
        "status": "skipped",
        "label": "unknown",
        "phishing_probability": None,
        "signals": [],
        "top_features": [],
        "model_version": "message-not-run",
        "error": "message analysis is not enabled for the local_url backend",
    }


def _build_summary(url_analysis: list[dict]) -> str:
    if not url_analysis:
        return "No URLs were available for local URL analysis."
    risky = [
        item
        for item in url_analysis
        if item.get("label") in {"suspicious", "malicious"}
        and item.get("status") == "success"
    ]
    if risky:
        return f"Local URL analysis found {len(risky)} risky URL candidate(s)."
    if any(item.get("status") != "success" for item in url_analysis):
        return "Local URL analysis completed with one or more URL failures."
    return "Local URL analysis did not find high-risk URL candidates."


def _build_risk_reasons(url_analysis: list[dict]) -> list[str]:
    if not url_analysis:
        return ["No URL candidates were extracted from the input."]

    reasons: list[str] = []
    for item in url_analysis:
        if item.get("display_href_mismatch"):
            reasons.append(
                "Displayed link text and actual destination domain do not match."
            )
        if item.get("status") != "success":
            reasons.append(f"URL analysis failed for {item.get('url', 'unknown URL')}.")
            continue
        score = item.get("risk_score")
        label = item.get("label", "unknown")
        if isinstance(score, (int, float)):
            reasons.append(
                f"{item.get('url', 'URL')} was classified as {label} "
                f"with a {score:.0%} risk score."
            )
    return list(dict.fromkeys(reasons))[:5]


def _recommended_actions(url_analysis: list[dict]) -> list[str]:
    if not url_analysis:
        return ["Continue with message analysis once the local message model is enabled."]
    return [
        "Do not open suspicious links directly from the message or email.",
        "Verify the destination through the organization's official website or app.",
        "Use the URL model result as a signal, not as a final phishing determination.",
    ]


def _build_errors(url_analysis: list[dict]) -> list[dict]:
    errors: list[dict] = []
    for item in url_analysis:
        if item.get("status") == "success":
            continue
        errors.append(
            {
                "code": "URL_MODEL_FAILED",
                "message": item.get("error") or "URL analysis failed",
                "url": item.get("url"),
            }
        )
    return errors
