import joblib

MODEL_PATH = "models/sms_spam_model.pkl"

model = joblib.load(MODEL_PATH)

# 피싱 판정 임계값
DEFAULT_THRESHOLD = 0.5

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
            "부업"
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

def extract_top_features(text: str) -> list:

    try:

        tfidf = model.named_steps["tfidf"]
        clf = model.named_steps["clf"]

        x = tfidf.transform([text])

        feature_names = tfidf.get_feature_names_out()

        spam_idx = 1

        features = []

        for idx in x.nonzero()[1]:

            score = float(
                clf.feature_log_prob_[spam_idx][idx]
            )

            name = feature_names[idx]

            if len(name.strip()) < 2:
                continue

            features.append(
                {
                    "name": name,
                    "score": score,
                }
            )

        features = sorted(
            features,
            key=lambda x: x["score"],
            reverse=True,
        )

        selected = []

        for feature in features:

            duplicated = False

            for existing in selected:

                if (
                    feature["name"] in existing
                    or existing in feature["name"]
                ):
                    duplicated = True
                    break

            if duplicated:
                continue

            selected.append(feature["name"])

            if len(selected) >= 3:
                break

        return selected

    except Exception:

        return []

def analyze_sms(text: str) -> dict:

    try:

        # 입력값 검증
        if not text or not text.strip():
            return {
                "status": "error",
                "label": "unknown",
                "phishing_probability": None,
                "signals": [],
                "top_features": [],
                "model_version": "sms-v1",
                "error": "empty_text",
            }

        # 피싱 확률 예측
        phishing_prob = float(
            model.predict_proba([text])[0][1]
        )

        # 최종 라벨 결정
        label = (
            "phishing"
            if phishing_prob >= DEFAULT_THRESHOLD
            else "normal"
        )

        # 피싱 문자 위험 신호 추출
        signals = []

        if label == "phishing":

            lowered_text = text.lower()

            for signal_name, keywords in SIGNAL_RULES:

                matched = any(
                    keyword.lower() in lowered_text
                    for keyword in keywords
                )

                if matched:
                    signals.append(signal_name)

        # top feature 제공
        top_features = extract_top_features(text)

        # 분석 결과 반환
        return {
            "status": "success",
            "label": label,
            "phishing_probability": phishing_prob,
            "signals": signals,
            "top_features": top_features,
            "model_version": "sms-v1",
            "error": None,
        }

    except Exception:

        # 안전한 오류 정보 반환
        return {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": [],
            "top_features": [],
            "model_version": "sms-v1",
            "error": "sms analysis failed",
        }