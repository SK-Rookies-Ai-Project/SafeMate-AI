"""예측, 위험 점수, 판단 근거 생성.

프로그램 흐름의 출력 단계: URL 배열 + 학습된 ModelBundle →
{url: '위험'/'안전'} 딕셔너리 (analyze_urls) 또는 상세 결과 (predict_urls).
"""

import re
from typing import Optional, Sequence

from src.analyzers.url import features
from src.analyzers.url.constants import (
    BENIGN_LABELS,
    RISK_VERDICT,
    SAFE_VERDICT,
    SENSITIVE_WORDS,
)
from src.analyzers.url.schemas import ModelBundle


def is_benign_label(label) -> bool:
    return str(label) in BENIGN_LABELS


_SCHEME_PATTERN = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")


def non_http_scheme(url: str) -> Optional[str]:
    """http/https가 아닌 명시적 스킴이면 그 스킴을 반환 (정책상 무조건 위험).

    'example.com:8080/x' 같은 호스트:포트는 스킴으로 오인하지 않는다 —
    '://' 없이 나온 스킴에 '.'이 있으면 호스트로 간주.
    """
    url = features.clean_url(url)
    m = _SCHEME_PATTERN.match(url)
    if not m:
        return None
    scheme = m.group(1).lower()
    if scheme in ("http", "https"):
        return None
    if "://" not in url[: m.end() + 2] and "." in scheme:
        return None  # 'example.com:8080/x' 류
    return scheme


def _risk_reasons(url: str) -> list:
    """규칙 기반 판단 근거 (모델과 별개로, 사용자 안내용)."""
    feats = features.extract_url_features(url)
    lower = features.clean_url(url).lower()
    reasons = []
    scheme = non_http_scheme(url)
    if scheme:
        reasons.append(f"웹 주소가 아닌 '{scheme}:' 스킴입니다 (스크립트 실행 등 위험).")
    if feats["executable"]:
        reasons.append("실행 파일을 가리키는 URL입니다.")
    if feats["URL_sensitiveWord"]:
        found = [w for w in SENSITIVE_WORDS if w in lower][:3]
        reasons.append(f"피싱에 자주 쓰이는 단어 포함: {', '.join(found)}")
    if feats["host_letter_count"] == 0 and feats["host_DigitCount"] > 0:
        reasons.append("도메인이 IP 주소입니다 (정상 서비스는 드묾).")
    if "@" in lower:
        reasons.append("'@' 문자로 실제 접속지를 숨겼을 수 있습니다.")
    if feats["urlLen"] >= 100:
        reasons.append(f"URL이 비정상적으로 깁니다 ({feats['urlLen']}자).")
    if feats["NumberRate_URL"] > 0.3:
        reasons.append("URL에 숫자 비율이 매우 높습니다.")
    if "xn--" in lower:
        reasons.append("퓨니코드(국제화 도메인)로 위장했을 수 있습니다.")
    return reasons


def predict_urls(
    bundle: ModelBundle,
    urls: Sequence[str],
    with_reasons: bool = True,
) -> list:
    """URL 배열을 예측해 상세 결과 리스트를 반환 (디버그/UI용).

    각 원소: {url, label, verdict, risk_score, reasons}
    - risk_score: 1 - P(정상). 확률 미지원 모델이면 위험 예측 시 1.0/0.0.
    """
    urls = list(urls)
    if not urls:
        return []
    labels = bundle.predict_labels(urls)
    proba = bundle.predict_proba(urls)

    results = []
    for i, url in enumerate(urls):
        label = labels[i]
        benign = is_benign_label(label)
        if proba is not None:
            benign_cols = [c for c in proba.columns if is_benign_label(c)]
            risk_score = float(1.0 - proba.iloc[i][benign_cols].sum())
        else:
            risk_score = 0.0 if benign else 1.0
        # 정책: http/https 외 스킴은 모델 판정과 무관하게 위험
        if non_http_scheme(url):
            benign = False
            risk_score = 1.0
        results.append({
            "url": url,
            "label": str(label),
            "verdict": SAFE_VERDICT if benign else RISK_VERDICT,
            "risk_score": round(risk_score, 4),
            "reasons": _risk_reasons(url) if with_reasons else [],
        })
    return results


def analyze_urls(bundle: ModelBundle, urls: Sequence[str]) -> dict:
    """프로그램 출력 형식: {링크: '위험'/'안전', ...} 딕셔너리."""
    return {r["url"]: r["verdict"] for r in predict_urls(bundle, urls, with_reasons=False)}
