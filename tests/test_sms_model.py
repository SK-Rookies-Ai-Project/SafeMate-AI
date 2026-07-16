"""
analyze_message.py 에서 `from sms_model import analyze_sms` 로 불러쓰는
SMS 스캠(스팸/피싱) 탐지 프로덕션 모듈.

학습/실험 코드는 여기 없습니다 (train_experiments.py, train_and_export_model.py 참고).
이 파일은 오직 sms_spam_model.pkl을 로드해서 문자 한 건을 판독하는 역할만 합니다.
"""

import os
import re

import joblib

MODEL_VERSION = "sms-v1"
_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sms_spam_model.pkl")

_model = None  # 최초 호출 시 한 번만 로드


def _get_model():
    global _model
    if _model is None:
        _model = joblib.load(_MODEL_PATH)
    return _model


# --------------------------------------------------------------------
# 규칙 기반 보조 시그널
# ML 확률 하나만 보여주면 챗봇이 "왜 스팸이라고 판단했는지" 설명하기
# 어려워서, 자주 나타나는 패턴을 별도로 탐지해 signals에 같이 담는다.
# ML 판정과는 독립적이며, 참고용 근거로만 사용.
# --------------------------------------------------------------------
_SIGNAL_PATTERNS = {
    "url_or_link": re.compile(r"(https?://|www\.|bit\.ly|\.kr\b|\.com\b)", re.IGNORECASE),
    "phone_number": re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}"),
    "urgency_keyword": re.compile(r"(즉시|긴급|지금\s*확인|바로\s*확인|한정|마감)"),
    "money_keyword": re.compile(r"(대출|입금|환급|당첨|무료|상품권|이벤트|캐시백)"),
    "messenger_contact": re.compile(r"(텔레그램|카톡|라인)\s*(문의|상담|@)"),
    "impersonation_keyword": re.compile(r"(국외발신|해외\s*로그인|계정\s*정지|본인\s*인증)"),
}


def _detect_signals(text: str) -> list[str]:
    return [name for name, pattern in _SIGNAL_PATTERNS.items() if pattern.search(text)]


def _get_top_features(pipeline, text: str, top_n: int = 5) -> list[dict]:
    """
    이 문장에서 스팸 판정에 가장 크게 기여한 n-gram을 근사적으로 추출.
    (TF-IDF 값 * 분류기 계수로 기여도를 근사, 계수를 못 구하면 빈 리스트 반환)
    """
    try:
        tfidf = pipeline.named_steps["tfidf"]
        clf = pipeline.named_steps["clf"]

        vec = tfidf.transform([text])
        feature_names = tfidf.get_feature_names_out()

        coefs = None
        if hasattr(clf, "calibrated_classifiers_"):
            # CalibratedClassifierCV로 감싼 경우: 폴드별 base 분류기 계수를 평균
            coef_list = []
            for cc in clf.calibrated_classifiers_:
                base = getattr(cc, "estimator", None) or getattr(cc, "base_estimator", None)
                if base is not None and hasattr(base, "coef_"):
                    coef_list.append(base.coef_[0])
            if coef_list:
                coefs = sum(coef_list) / len(coef_list)
        elif hasattr(clf, "coef_"):
            coefs = clf.coef_[0]

        if coefs is None:
            return []

        contrib = vec.multiply(coefs).toarray()[0]
        nonzero_idx = contrib.nonzero()[0]
        if len(nonzero_idx) == 0:
            return []

        ranked = nonzero_idx[contrib[nonzero_idx].argsort()[::-1]]
        top_idx = [i for i in ranked if contrib[i] > 0][:top_n]

        return [
            {"feature": feature_names[i], "weight": round(float(contrib[i]), 4)}
            for i in top_idx
        ]
    except Exception:
        return []


def analyze_sms(text: str) -> dict:
    """
    SMS 문자 한 건을 분석해서 스팸/피싱 여부를 판정한다.
    analyze_message.py가 기대하는 응답 스키마를 그대로 따른다.

    Returns:
        {
            "status": "success" | "error",
            "label": "spam" | "ham" | "unknown",
            "phishing_probability": float | None,
            "signals": list[str],
            "top_features": list[dict],
            "model_version": str,
            "error": str  # status == "error" 일 때만 포함
        }
    """
    if not text or not text.strip():
        return {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": [],
            "top_features": [],
            "model_version": MODEL_VERSION,
            "error": "empty text",
        }

    try:
        model = _get_model()
        proba = float(model.predict_proba([text])[0][1])  # 스팸(1)일 확률
        label = "spam" if proba > 0.5 else "ham"

        return {
            "status": "success",
            "label": label,
            "phishing_probability": round(proba, 4),
            "signals": _detect_signals(text),
            "top_features": _get_top_features(model, text),
            "model_version": MODEL_VERSION,
        }

    except FileNotFoundError:
        return {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": [],
            "top_features": [],
            "model_version": MODEL_VERSION,
            "error": f"model file not found: {_MODEL_PATH}",
        }
    except Exception:
        return {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": [],
            "top_features": [],
            "model_version": MODEL_VERSION,
            "error": "analysis failed",
        }


if __name__ == "__main__":
    samples = [
        "엄마 나 폰이 망가져서 컴퓨터로 문자 보내고 있어",
        "[국외발신] 계정이 해외 IP에서 로그인되었습니다. 지금 확인하세요 http://bit.ly/abc123",
    ]
    for s in samples:
        print(s)
        print(analyze_sms(s))
        print("---")
