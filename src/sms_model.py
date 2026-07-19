import math
import joblib

MODEL_PATH = "models/sms_spam_model.pkl"

_model = None

MODEL_VERSION = "sms-v1"

# 최적 임계값
BEST_THRESHOLD = 0.9621


# 모델을 한 번만 로드하여 재사용
def _get_model():

    global _model

    if _model is None:
        _model = joblib.load(MODEL_PATH)

    return _model


# 공통 에러 반환
def _error_result(error: str) -> dict:

    return {
        "status": "error",
        "label": "unknown",
        "phishing_probability": None,
        "signals": [],
        "top_features": [],
        "model_version": MODEL_VERSION,
        "error": error,
    }


# 위험 신호 규칙
SIGNAL_RULES = [
    (
        "개인정보 또는 인증정보 입력 요구",
        [
            "비밀번호",
            "인증",
            "인증번호",
            "otp",
            "보안코드",
            "주민번호",
            "주민등록번호",
            "카드번호",
            "계좌번호",
            "개인정보",
            "본인인증",
        ],
    ),
    (
        "긴급성을 강조하는 표현",
        [
            "긴급",
            "즉시",
            "지금",
            "오늘까지",
            "정지 예정",
            "차단 예정",
            "만료",
            "최종 경고",
        ],
    ),
    (
        "금전 또는 결제를 요구하는 표현",
        [
            "입금",
            "송금",
            "이체",
            "결제",
            "수수료",
            "상품권",
            "선납",
            "보증금",
            "대출",
        ],
    ),
    (
        "계정 제한 또는 차단을 경고하는 표현",
        [
            "계정 정지",
            "이용 정지",
            "접속 차단",
            "로그인 차단",
            "계정 잠금",
            "사용 제한",
        ],
    ),
    (
        "앱 또는 파일 실행을 유도하는 표현",
        [
            "앱 설치",
            "어플 설치",
            "apk",
            "원격제어",
            "원격 지원",
            "첨부파일 실행",
            "프로그램 설치",
        ],
    ),
    (
        "당첨·환급·고수익을 미끼로 한 표현",
        [
            "당첨",
            "환급금",
            "지원금",
            "보상금",
            "고수익",
            "수익 보장",
            "무료 쿠폰",
        ],
    ),
    (
        "취업 또는 채용 관련 표현",
        [
            "채용",
            "구인",
            "구직",
            "인사담당자",
            "재택근무",
            "부업",
        ],
    ),
    (
        "기관 사칭 가능성",
        [
            "국세청",
            "검찰",
            "경찰",
            "금융감독원",
        ],
    ),
    (
        "도박 또는 토토 관련 표현",
        [
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
        ],
    ),
    (
        "URL 또는 외부 접속 유도 표현",
        [
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
        ],
    ),
]

# TF-IDF와 Naive Bayes를 이용해 상위 특징 추출
def extract_top_features(text: str) -> list:

    try:

        model = _get_model()

        tfidf = model.named_steps["tfidf"]
        clf = model.named_steps["clf"]

        x = tfidf.transform([text])

        feature_names = tfidf.get_feature_names_out()

        normal_idx = 0
        phishing_idx = 1

        features = []

        for idx in x.nonzero()[1]:

            name = feature_names[idx].strip()

            # 의미 없는 토큰 제거
            if len(name) < 2:
                continue

        
            # 피싱 클래스 기여도 계산        
            contribution = float(
                clf.feature_log_prob_[phishing_idx][idx]
                - clf.feature_log_prob_[normal_idx][idx]
            )

            # 피싱에 기여한 단어만 선택
            if contribution <= 0:
                continue

            features.append(
                {
                    "name": name,
                    "value": round(
                        float(x[0, idx]),
                        4,
                    ),
                    "contribution": round(
                        contribution,
                        4,
                    ),
                }
            )

        # 기여도가 높은 순 정렬
        features.sort(
            key=lambda x: x["contribution"],
            reverse=True,
        )

        selected = []

        # 중복 제거 후 상위 3개 반환
        for feature in features:

            duplicated = False

            for existing in selected:

                if (
                    feature["name"] in existing["name"]
                    or existing["name"] in feature["name"]
                ):
                    duplicated = True
                    break

            if duplicated:
                continue

            selected.append(feature)

            if len(selected) == 3:
                break

        return selected

    except Exception:

        return []
    
# SMS 피싱 분석
def analyze_sms(text: str) -> dict:

    try:
        # 입력값 검증
        if not text or not text.strip():
            return _error_result("empty_text")

        text = text.strip()

        model = _get_model()

        # 피싱 확률 예측
        phishing_prob = float(
            model.predict_proba([text])[0][1]
        )

        if (
            not math.isfinite(phishing_prob)
            or phishing_prob < 0
            or phishing_prob > 1
        ):
            raise ValueError("invalid_probability")
        # 예측 결과에 따른 라벨 결정
        label = (
            "phishing"
            if phishing_prob > BEST_THRESHOLD
            else "normal"
        )

        signals = []

        # 피싱으로 판단된 경우 위험 신호 탐지
        if label == "phishing":

            lowered_text = text.lower()

            for signal_name, keywords in SIGNAL_RULES:

                if any(
                    keyword.lower() in lowered_text
                    for keyword in keywords
                ):
                    signals.append(signal_name)

        signals = list(dict.fromkeys(signals))
        # 사용자에게 보여줄 상위 특징 추출
        top_features = extract_top_features(text)

        return {
            "status": "success",
            "label": label,
            "phishing_probability": round(
                phishing_prob,
                2,
            ),
            "signals": signals,
            "top_features": top_features,
            "model_version": MODEL_VERSION,
            "error": None,
        }

    except Exception as e:

        return _error_result(str(e))