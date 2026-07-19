"""Shared helpers for local SMS and email classification models."""

from __future__ import annotations

import math
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib


SIGNAL_RULES = (
    (
        "개인정보 또는 인증정보 입력 요구",
        (
            "비밀번호",
            "인증번호",
            "otp",
            "보안코드",
            "주민번호",
            "주민등록번호",
            "카드번호",
            "계좌번호",
            "개인정보",
            "본인인증",
            "인증",
        ),
    ),
    (
        "긴급성을 강조하는 표현",
        (
            "긴급",
            "즉시",
            "지금",
            "오늘까지",
            "정지 예정",
            "차단 예정",
            "만료",
            "최종 경고",
        ),
    ),
    (
        "금전 또는 결제를 요구하는 표현",
        ("입금", "송금", "이체", "결제", "수수료", "상품권", "선납", "보증금", "대출"),
    ),
    (
        "계정 제한 또는 차단을 경고하는 표현",
        ("계정 정지", "이용 정지", "접속 차단", "로그인 차단", "계정 잠금", "사용 제한"),
    ),
    (
        "앱 또는 파일 실행을 유도하는 표현",
        ("앱 설치", "어플 설치", "apk", "원격제어", "원격 지원", "첨부파일 실행", "프로그램 설치"),
    ),
    (
        "당첨·환급·고수익을 미끼로 한 표현",
        ("당첨", "환급금", "지원금", "보상금", "고수익", "수익 보장", "무료 쿠폰"),
    ),
    ("취업 또는 채용 관련 표현", ("채용", "구인", "구직", "인사담당자", "재택근무", "부업")),
    ("기관 사칭 가능성", ("국세청", "검찰", "경찰", "금융감독원")),
    (
        "도박 또는 투자 유도 표현",
        (
            "토토",
            "스포츠토토",
            "카지노",
            "배팅",
            "베팅",
            "적중",
            "고정픽",
            "vip",
            "당첨번호",
            "코인",
            "비트코인",
            "주식",
            "수익률",
            "트레이딩",
            "텔레그램",
        ),
    ),
    (
        "URL 또는 외부 접속 유도 표현",
        (
            "링크",
            "접속",
            "클릭",
            "바로가기",
            "확인하기",
            "조회하기",
            "인증하기",
            "로그인하기",
            "http",
            "https",
        ),
    ),
)

TopFeatureExtractor = Callable[[Any, str], list[dict[str, Any]]]


@lru_cache(maxsize=4)
def _load_model(model_path: str) -> Any:
    return joblib.load(model_path)


def analyze_with_model(
    text: str,
    *,
    model_path: Path,
    model_version: str,
    unavailable_message: str,
    failure_message: str,
    threshold: float = 0.5,
    threshold_inclusive: bool = True,
    top_feature_extractor: TopFeatureExtractor | None = None,
) -> dict:
    """Run a binary classifier and return the shared message-model contract."""
    try:
        model = _load_model(str(model_path))
        probabilities = model.predict_proba([text])[0]
        classes = list(getattr(model, "classes_", (0, 1)))
        phishing_index = classes.index(1) if 1 in classes else len(probabilities) - 1
        probability = float(probabilities[phishing_index])
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ValueError("invalid probability")

        is_phishing = probability >= threshold if threshold_inclusive else probability > threshold
        label = "phishing" if is_phishing else "normal"
        signals = _detect_signals(text) if label == "phishing" else []
        top_features = top_feature_extractor(model, text) if top_feature_extractor else []
        return {
            "status": "success",
            "label": label,
            "phishing_probability": probability,
            "signals": signals,
            "top_features": top_features,
            "model_version": model_version,
            "error": None,
        }
    except FileNotFoundError:
        return _error_result(
            model_version,
            code="MODEL_NOT_AVAILABLE",
            message=unavailable_message,
        )
    except Exception:
        return _error_result(
            model_version,
            code="MODEL_INFERENCE_FAILED",
            message=failure_message,
        )


def extract_email_top_features(model: Any, text: str) -> list[dict[str, Any]]:
    """Return the strongest non-trivial TF-IDF contributions for the email model."""
    try:
        tfidf = model.named_steps["tfidf"]
        classifier = model.named_steps["model"]
        vector = tfidf.transform([text])
        feature_names = tfidf.get_feature_names_out()
        coefficients = classifier.coef_[0]
        candidates = []
        for index in vector.nonzero()[1]:
            name = str(feature_names[index]).replace("word_tfidf__", "").replace("char_tfidf__", "").strip()
            contribution = float(vector[0, index] * coefficients[index])
            if len(name) < 2 or abs(contribution) < 0.05:
                continue
            candidates.append(
                {
                    "name": name,
                    "value": round(float(vector[0, index]), 4),
                    "contribution": round(abs(contribution), 4),
                }
            )
        return _select_distinct_features(candidates)
    except Exception:
        return []


def extract_sms_top_features(model: Any, text: str) -> list[dict[str, Any]]:
    """Return TF-IDF tokens that favor the SMS phishing class."""
    try:
        tfidf = model.named_steps["tfidf"]
        classifier = model.named_steps["clf"]
        vector = tfidf.transform([text])
        feature_names = tfidf.get_feature_names_out()
        classes = list(getattr(classifier, "classes_", getattr(model, "classes_", (0, 1))))
        normal_index = classes.index(0)
        phishing_index = classes.index(1)
        candidates = []
        for index in vector.nonzero()[1]:
            name = str(feature_names[index]).split("__", 1)[-1].strip()
            contribution = float(
                classifier.feature_log_prob_[phishing_index][index]
                - classifier.feature_log_prob_[normal_index][index]
            )
            if len(name) < 2 or contribution <= 0:
                continue
            candidates.append(
                {
                    "name": name,
                    "value": round(float(vector[0, index]), 4),
                    "contribution": round(contribution, 4),
                }
            )
        return _select_distinct_features(candidates)
    except Exception:
        return []


def _select_distinct_features(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: item["contribution"], reverse=True):
        name = candidate["name"]
        if any(name in item["name"] or item["name"] in name for item in selected):
            continue
        selected.append(candidate)
        if len(selected) == 3:
            break
    return selected


def _detect_signals(text: str) -> list[str]:
    lowered_text = text.lower()
    return [
        signal_name
        for signal_name, keywords in SIGNAL_RULES
        if any(keyword.lower() in lowered_text for keyword in keywords)
    ]


def _error_result(model_version: str, *, code: str, message: str) -> dict:
    return {
        "status": "error",
        "label": "unknown",
        "phishing_probability": None,
        "signals": [],
        "top_features": [],
        "model_version": model_version,
        "error": {
            "code": code,
            "message": message,
            "retryable": False,
        },
    }
