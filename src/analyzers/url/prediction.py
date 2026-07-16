"""Prediction helpers for trained URL ModelBundle objects."""

import math
import re
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

from src.analyzers.url.constants import (
    BENIGN_LABELS,
    EXECUTABLE_EXTENSIONS,
    RISK_VERDICT,
    SAFE_VERDICT,
    SENSITIVE_WORDS,
)
from src.analyzers.url.features import extract_url_features, normalize_url
from src.analyzers.url.reputation import lookup_url_reputation
from src.analyzers.url.schemas import ModelBundle

MODEL_VERSION = "url-v1"

_DISPLAY_FEATURES = (
    ("URL 길이", "urlLen", 120.0),
    ("도메인 길이", "domainlength", 60.0),
    ("경로 길이", "pathLength", 90.0),
    ("쿼리 길이", "Querylength", 120.0),
    ("특수문자 개수", "SymbolCount_URL", 24.0),
    ("숫자 비율", "NumberRate_URL", 1.0),
    ("점 개수", "NumberofDotsinURL", 8.0),
    ("민감 키워드 개수", "URL_sensitiveWord", 4.0),
    ("쿼리 변수 개수", "URLQueries_variable", 8.0),
    ("URL 엔트로피", "Entropy_URL", 1.0),
    ("실행 파일 확장자", "executable", 1.0),
)
_SUPPORTED_SCHEMES = frozenset({"http", "https"})
_WHITESPACE_RE = re.compile(r"\s")


def _empty_contract(url: Any, error: Optional[str]) -> dict:
    return {
        "status": "error" if error else "success",
        "url": url if isinstance(url, str) else "",
        "label": "unknown",
        "risk_score": None,
        "signals": [],
        "features": [],
        "model_version": MODEL_VERSION,
        "error": error,
    }


def validate_url(url: Any) -> Optional[str]:
    """Return a safe user-facing error string, or None when usable."""
    if not isinstance(url, str):
        return "url must be a string"
    raw = url.strip()
    if not raw:
        return "url is empty"
    if _WHITESPACE_RE.search(raw):
        return "url contains whitespace"
    try:
        parsed = urlparse(normalize_url(raw))
        scheme = parsed.scheme.lower()
        host = parsed.hostname
    except Exception:
        return "url is invalid"
    if scheme not in _SUPPORTED_SCHEMES:
        return "url scheme is not supported"
    if not host or "." not in host:
        return "url host is invalid"
    return None


def _json_number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    return value


def _normalize_feature_value(raw_value: Any, scale: float) -> float:
    if raw_value is None:
        return 0.0
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value) or math.isinf(value) or value <= 0:
        return 0.0
    return round(min(value / scale, 1.0), 4)


def explain_lexical_features(url: str) -> list[dict]:
    """Features actually extracted for the URL, formatted for the UI contract."""
    raw_features = extract_url_features(url)
    return [
        {
            "name": display_name,
            "raw_value": _json_number(raw_features.get(feature_name)),
            "normalized_value": _normalize_feature_value(
                raw_features.get(feature_name), scale
            ),
            "contribution": None,
        }
        for display_name, feature_name, scale in _DISPLAY_FEATURES
    ]


def _model_step(model: Any, name: str) -> Any:
    if hasattr(model, "named_steps"):
        return model.named_steps.get(name)
    return None


def _risk_contributions_for_tfidf(bundle: ModelBundle, x_row) -> Optional[dict[int, float]]:
    """Return per-column risk contributions when the model exposes them safely."""
    logistic = _model_step(bundle.model, "logisticregression")
    scaler = _model_step(bundle.model, "standardscaler")
    if logistic is None or scaler is None:
        return None
    if not hasattr(logistic, "coef_") or len(getattr(logistic, "classes_", [])) != 2:
        return None

    classes = list(logistic.classes_)
    decoded = (
        [str(v) for v in bundle.label_encoder.inverse_transform(classes)]
        if bundle.label_encoder is not None
        else [str(v) for v in classes]
    )
    benign_labels = {str(v).lower() for v in BENIGN_LABELS}
    positive_label = decoded[1].strip().lower()
    positive_is_risk = positive_label not in benign_labels

    scaled = scaler.transform(x_row)
    coef = logistic.coef_[0]
    row = scaled.multiply(coef).tocoo()
    sign = 1.0 if positive_is_risk else -1.0
    return {int(col): float(value * sign) for col, value in zip(row.col, row.data)}


def explain_tfidf_features(bundle: ModelBundle, url: str, limit: int = 10) -> list[dict]:
    """Return TF-IDF n-gram features actually passed to the URL model."""
    if bundle.vectorizer is None:
        return []

    x_row = bundle.transform([url])
    if x_row.shape[0] == 0 or x_row.nnz == 0:
        return []

    feature_names = bundle.vectorizer.get_feature_names_out()
    contributions = _risk_contributions_for_tfidf(bundle, x_row)
    coo = x_row.tocoo()
    rows = []
    for col, value in zip(coo.col, coo.data):
        contribution = None
        if contributions is not None:
            contribution = round(contributions.get(int(col), 0.0), 6)
        rows.append({
            "name": f"TF-IDF ngram: {feature_names[int(col)]}",
            "raw_value": float(value),
            "normalized_value": round(min(max(float(value), 0.0), 1.0), 4),
            "contribution": contribution,
        })

    if contributions is not None:
        rows.sort(key=lambda row: abs(row["contribution"] or 0.0), reverse=True)
    else:
        rows.sort(key=lambda row: row["raw_value"], reverse=True)
    return rows[:limit]


def explain_features(bundle: ModelBundle, url: str) -> list[dict]:
    """Return the feature rows that match the active model representation."""
    if bundle.kind == "tfidf":
        return explain_tfidf_features(bundle, url)
    return explain_lexical_features(url)


def build_signals(url: str) -> list[str]:
    """Human-readable string-feature signals. No URL requests are performed."""
    raw = url.strip()
    parsed = urlparse(normalize_url(raw))
    host = parsed.hostname or ""
    path = parsed.path or ""
    query = parsed.query or ""
    lower = raw.lower()
    signals = []

    if len(raw) >= 80:
        signals.append("URL 길이가 김")
    if any(word in lower for word in SENSITIVE_WORDS):
        signals.append("로그인 또는 계정 관련 키워드 포함")
    if query:
        signals.append("쿼리 문자열 포함")
    if sum(not ch.isalnum() for ch in raw) >= 10:
        signals.append("특수문자 사용 비율이 높음")
    if sum(ch.isdigit() for ch in host) >= 4:
        signals.append("도메인에 숫자가 많이 포함됨")
    if host.replace(".", "").isdigit():
        signals.append("IP 주소 형태의 도메인 사용")
    if path.rsplit(".", 1)[-1].lower() in EXECUTABLE_EXTENSIONS:
        signals.append("실행 파일 확장자 포함")
    if parsed.scheme.lower() == "http":
        signals.append("암호화되지 않은 HTTP 스킴 사용")
    return signals


def label_to_verdict(label) -> str:
    """Map a source label to the legacy Korean verdict."""
    return SAFE_VERDICT if str(label) in BENIGN_LABELS else RISK_VERDICT


def predict_urls(bundle: ModelBundle, urls: Sequence[str]) -> list:
    """Return legacy detailed prediction rows for multiple URLs."""
    urls = list(urls)
    labels = bundle.predict_labels(urls)
    proba = bundle.predict_proba(urls)

    results = []
    for i, (url, label) in enumerate(zip(urls, labels)):
        risk_score = None
        proba_row = None
        if proba is not None:
            proba_row = {str(c): float(p) for c, p in proba.iloc[i].items()}
            risk_score = sum(
                p for c, p in proba_row.items() if c not in BENIGN_LABELS
            )
        results.append({
            "url": url,
            "label": str(label),
            "verdict": label_to_verdict(label),
            "risk_score": risk_score,
            "proba": proba_row,
        })
    return results


def label_to_contract_label(label: Any, risk_score: Optional[float]) -> str:
    label_text = str(label).strip().lower()
    benign_labels = {str(v).lower() for v in BENIGN_LABELS}
    if label_text in benign_labels:
        return "benign"
    if label_text in {"malware", "malicious", "bad", "악성"}:
        return "malicious"
    if label_text in {"phishing", "spam", "suspicious", "위험", "낚시"}:
        return "suspicious"
    if risk_score is None:
        return "unknown"
    return "malicious" if risk_score >= 0.85 else "suspicious"


def analyze_url(bundle: ModelBundle, url: str) -> dict:
    """Single URL inference result matching the SafeMate UI contract."""
    validation_error = validate_url(url)
    if validation_error:
        return _empty_contract(url, validation_error)

    try:
        prediction = predict_urls(bundle, [url])[0]
        risk_score = prediction["risk_score"]
        if risk_score is not None:
            risk_score = round(max(0.0, min(float(risk_score), 1.0)), 4)
        label = label_to_contract_label(prediction["label"], risk_score)
        signals = build_signals(url)
        reputation = lookup_url_reputation(url)
        if reputation is not None:
            risk_score = round(
                max(0.0, min(float(reputation["risk_score"]), 1.0)),
                4,
            )
            label = label_to_contract_label(reputation["label"], risk_score)
            signals.append(
                "로컬 URL 데이터셋 exact match: "
                f"{reputation['label']} "
                f"({reputation['benign_count']} 정상 / "
                f"{reputation['risk_count']} 악성)"
            )
        return {
            "status": "success",
            "url": url,
            "label": label,
            "risk_score": risk_score,
            "signals": signals,
            "features": explain_features(bundle, url),
            "model_version": MODEL_VERSION,
            "error": None,
        }
    except Exception:
        return _empty_contract(url, "url analysis failed")


def analyze_urls(bundle: ModelBundle, urls: Sequence[str]) -> dict:
    """Return the legacy URL-to-verdict mapping."""
    return {r["url"]: r["verdict"] for r in predict_urls(bundle, urls)}
