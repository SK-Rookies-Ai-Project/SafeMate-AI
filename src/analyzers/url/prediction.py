"""학습된 ModelBundle로 URL 위험도를 판정하는 예측 모듈."""

from typing import Sequence

from src.analyzers.url.constants import (
    BENIGN_LABELS,
    RISK_VERDICT,
    SAFE_VERDICT,
)
from src.analyzers.url.schemas import ModelBundle


def label_to_verdict(label) -> str:
    """원본 라벨 → '위험'/'안전' 판정 (BENIGN_LABELS 외에는 전부 위험)."""
    return SAFE_VERDICT if str(label) in BENIGN_LABELS else RISK_VERDICT


def predict_urls(bundle: ModelBundle, urls: Sequence[str]) -> list:
    """상세 예측 결과 리스트 — 디버그/UI용.

    각 원소: {url, label(원본 라벨), verdict(위험/안전),
              risk_score(위험 클래스 확률 합, 모델 미지원 시 None),
              proba(클래스별 확률 dict, 모델 미지원 시 None)}
    """
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


def analyze_urls(bundle: ModelBundle, urls: Sequence[str]) -> dict:
    """URL 배열 → {링크: '위험'/'안전'} (프로그램 최종 출력 형식)."""
    return {r["url"]: r["verdict"] for r in predict_urls(bundle, urls)}
