"""Analysis pipeline orchestration and operational risk policy."""

from __future__ import annotations

import math
from numbers import Real
from typing import Any

from src.config import RISK_HIGH_THRESHOLD, RISK_MEDIUM_THRESHOLD


def calculate_overall_risk(
    message_analysis: dict[str, Any] | None,
    url_analysis: list[dict[str, Any]] | None,
) -> dict[str, float | str | None]:
    """Calculate overall risk from valid local-model scores only.

    Search evidence and generated text are deliberately excluded. Invalid,
    non-finite, and out-of-range values are ignored instead of being clamped.
    """
    scores: list[float] = []

    if isinstance(message_analysis, dict):
        score = _valid_score(message_analysis.get("phishing_probability"))
        if score is not None:
            scores.append(score)

    if isinstance(url_analysis, list):
        for analysis in url_analysis:
            if not isinstance(analysis, dict):
                continue
            score = _valid_score(analysis.get("risk_score"))
            if score is not None:
                scores.append(score)

    if not scores:
        return {"score": None, "level": "unknown"}

    score = max(scores)
    if score >= RISK_HIGH_THRESHOLD:
        level = "high"
    elif score >= RISK_MEDIUM_THRESHOLD:
        level = "medium"
    else:
        level = "low"
    return {"score": score, "level": level}


def _valid_score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        return None
    return score
