
# 응답 스키마는 팀 UI 챗봇 연동 규격을 따릅니다:
#     {
#         "status": "success" | "error",
#         "label": "phishing" | "normal" | "unknown",
#         "phishing_probability": float | None,
#         "signals": list[str],           # 한국어 설명 문구
#         "top_features": list[dict],     # {"name", "value", "contribution"}
#         "model_version": "message-v1",
#         "error": str | None,
#     }

#전처리와 준비에 필요한 import들
import os
import re
import joblib

MODEL_VERSION = "sms_model-v1"
_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sms_spam_model.pkl")

# train_and_export_model.py의 threshold 정책과 동일하게 유지
# (model_meta.json의 default_threshold와도 동일해야 함)
# threshold의 프로젝트 정책상 현재값은 0.5로 default와 같지만 변경가능하도록 변수로 지정
# threshold=0.5 기준 char-only보다 char+word 조합이 FP/FN 지표 모두 우세하여 char+word 합쳐서 전처리
# (Precision=0.9032, Recall=0.70, FP=9, FN=36 @ spam_test_master)
DEFAULT_THRESHOLD = 0.5

_model = None  # 최초 호출 시 한 번만 로드


def _get_model():
    global _model
    if _model is None:
        _model = joblib.load(_MODEL_PATH)
    return _model


# --------------------------------------------------------------------
# 시그널 패턴 정의 (필요시 사용될것)
# ML 확률 하나만 보여주면 챗봇이 "왜 피싱이라고 판단했는지" 설명하기
# 어려워서, 자주 나타나는 패턴을 별도로 탐지해 signals에 같이 담는다.
# ML 판정과는 독립적이며, 참고용 근거로만 사용.
# 키는 내부 식별용이고, 실제로 반환되는 건 한국어 설명 문구(값)임.
# --------------------------------------------------------------------
_SIGNAL_PATTERNS = {
    "url_or_link": (
        re.compile(r"(https?://|www\.|bit\.ly|\.kr\b|\.com\b)", re.IGNORECASE),
        "의심스러운 링크 포함",
    ),
    "phone_number": (
        re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}"),
        "전화번호 포함",
    ),
    "urgency_keyword": (
        re.compile(r"(즉시|긴급|지금\s*확인|바로\s*확인|한정|마감)"),
        "긴급성을 강조하는 표현",
    ),
    "money_keyword": (
        re.compile(r"(대출|입금|환급|당첨|무료|상품권|이벤트|캐시백)"),
        "금전/보상 관련 표현",
    ),
    "messenger_contact": (
        re.compile(r"(텔레그램|카톡|라인)\s*(문의|상담|@)"),
        "메신저 상담으로 유도하는 표현",
    ),
    "impersonation_keyword": (
        re.compile(r"(국외발신|해외\s*로그인|계정\s*정지|본인\s*인증)"),
        "기관/계정 사칭 표현",
    ),
    "personal_info_request": (
        re.compile(r"(비밀번호|인증번호|계좌번호|주민등록번호|카드번호|보안카드|OTP)", re.IGNORECASE),
        "개인정보 입력 요구",
    ),
}


def _detect_signals(text: str) -> list[str]:
    return [
        description
        for pattern, description in _SIGNAL_PATTERNS.values()
        if pattern.search(text)
    ]


def _get_preprocessor(tfidf_step):
    if hasattr(tfidf_step, "preprocessor"):
        return tfidf_step.preprocessor
    if hasattr(tfidf_step, "transformer_list"):
        for _, sub in tfidf_step.transformer_list:
            pre = getattr(sub, "preprocessor", None)
            if pre is not None:
                return pre
    return None

#char+word를 쓰기 때문에 필요한 처리. 어느 분류기에 걸린 것인지 표기해주는 문구는 사용자에게 노출할 이유 없음.
def _strip_union_prefix(name: str) -> str:
    for prefix in ("char__", "word__"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name

#top features 채워주는 함수(필요시 쓸수 있게 구현)
def _get_top_features(pipeline, text: str, top_n: int = 5) -> list[dict]:
    try:
        tfidf = pipeline.named_steps["tfidf"]
        clf = pipeline.named_steps["clf"]

        vec = tfidf.transform([text])
        tfidf_values = vec.toarray()[0]
        raw_feature_names = tfidf.get_feature_names_out()
        # FeatureUnion(char+word)인 경우 'char__'/'word__' 접두어가 붙으므로 제거
        feature_names = [_strip_union_prefix(str(n)) for n in raw_feature_names]

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
        elif hasattr(clf, "feature_log_prob_"):
            # MultinomialNB: coef_가 없어서 log-odds(피싱 클래스 - 정상 클래스)로 근사
            classes = list(clf.classes_)
            spam_idx = classes.index(1) if 1 in classes else 1
            ham_idx = classes.index(0) if 0 in classes else 0
            coefs = clf.feature_log_prob_[spam_idx] - clf.feature_log_prob_[ham_idx]

        if coefs is None:
            return []

        contrib = tfidf_values * coefs
        nonzero_idx = contrib.nonzero()[0]
        if len(nonzero_idx) == 0:
            return []

        # 기여도 높은 순으로 정렬
        ranked = nonzero_idx[contrib[nonzero_idx].argsort()[::-1]]
        candidates = [i for i in ranked if contrib[i] > 0][: top_n * 6]
        #왜 candidate를 많이 확보하는가?
        # 겹치는 n-gram 조각 제거: char n-gram(2~6)은 원문의 같은 구간에서
        # "http", "tt", "tp:/"처럼 서로 겹치는 조각이 동시에 후보로 올라와서
        # top_n 자리를 중복으로 채우는 문제가 있음. 각 후보가 실제로 벡터화에
        # 쓰인 텍스트(전처리 후 - URL이 'url'로 치환된 상태 등)에서 차지하는
        # 문자 구간(span)을 찾아서, 이미 선택된 항목과 구간이 겹치면 건너뛰고
        # 서로 겹치지 않는 구간만 최종 선택한다.
        # 주의: 전처리(preprocessor)가 설정돼 있으면(예: URL 치환) 원문(text)이
        # 아니라 전처리 결과 기준으로 위치를 찾아야 실제 벡터와 어긋나지 않음.
        # FeatureUnion(char+word)인 경우 tfidf 자체엔 preprocessor 속성이
        # 없으므로 서브 변환기에서 찾는다 (_get_preprocessor).
        preprocessor = _get_preprocessor(tfidf)
        if preprocessor is not None:
            match_text = preprocessor(text)
        elif getattr(tfidf, "lowercase", True):
            match_text = text.lower() if hasattr(text, "lower") else text
        else:
            match_text = text

        selected: list[int] = []
        selected_spans: list[tuple[int, int]] = []
        for i in candidates:
            name = str(feature_names[i]).strip()
            if not name:
                continue
            # TF-IDF는 기본적으로 소문자로 변환해서 어휘를 만들므로,
            # 원문에서 위치를 찾을 때도 소문자 기준으로 비교해야 함
            # (그렇지 않으면 "IP" 같은 대문자 구간의 겹침을 놓침)
            start = match_text.find(name)
            if start != -1:
                span = (start, start + len(name))
                if any(span[0] < s[1] and span[1] > s[0] for s in selected_spans):
                    continue
                selected_spans.append(span)
            else:
                # 원문에서 위치를 못 찾으면(공백 정규화 등으로) 문자열 포함 관계로 대체 확인
                if any(
                    name in str(feature_names[j]).strip() or str(feature_names[j]).strip() in name
                    for j in selected
                ):
                    continue
            selected.append(i)
            if len(selected) >= top_n:
                break

        top_idx = selected

        return [
            {
                "name": str(feature_names[i]),
                "value": round(float(tfidf_values[i]), 4),
                "contribution": round(float(contrib[i]), 4),
            }
            for i in top_idx
        ]
    except Exception:
        return []

#문자열(실제 테스트할 sms 내용)을 받아와 학습된 모델로 실제로 예측, 분류하기.
def analyze_sms(text: str) -> dict:
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
        proba = float(model.predict_proba([text])[0][1])  # 피싱(1)일 확률
        label = "phishing" if proba > DEFAULT_THRESHOLD else "normal"

        return {
            "status": "success",
            "label": label,
            "phishing_probability": round(proba, 4),
            "signals": _detect_signals(text),
            "top_features": _get_top_features(model, text),
            "model_version": MODEL_VERSION,
            "error": None,
        }

    except FileNotFoundError:
        return {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": [],
            "top_features": [],
            "model_version": MODEL_VERSION,
            "error": "model not available",
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

#본 파일로 단일 테스트 해볼때 샘플은 간단한것 두개.
if __name__ == "__main__":
    samples = [
        "엄마 나 폰이 망가져서 컴퓨터로 문자 보내고 있어",
        "[국외발신] 계정이 해외 IP에서 로그인되었습니다. 비밀번호와 인증번호를 지금 확인하세요 http://bit.ly/abc123",
    ]
    for s in samples:
        print(s)
        print(analyze_sms(s))
        print("---")
