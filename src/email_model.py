import joblib

MODEL_PATH = "models/email_spam_model.pkl"
model = joblib.load(MODEL_PATH)

# 피싱 판정 임계값
DEFAULT_THRESHOLD = 0.5

# 위험 신호 규칙
SIGNAL_RULES = [
    (
        "개인정보 또는 인증정보 입력 요구",
        [
            "비밀번호", "인증", "인증번호", "otp",
            "보안코드", "주민번호", "주민등록번호",
            "카드번호", "계좌번호", "개인정보", "본인인증",
        ],
    ),
    (
        "긴급성을 강조하는 표현",
        [
            "긴급", "즉시", "지금", "오늘까지",
            "정지 예정", "차단 예정", "만료", "최종 경고",
        ],
    ),
    (
        "금전 또는 결제를 요구하는 표현",
        [
            "입금", "송금", "이체", "결제",
            "수수료", "상품권", "선납",
            "보증금", "대출",
        ],
    ),
    (
        "계정 제한 또는 차단을 경고하는 표현",
        [
            "계정 정지", "이용 정지",
            "접속 차단", "로그인 차단",
            "계정 잠금", "사용 제한",
        ],
    ),
    (
        "앱 또는 파일 실행을 유도하는 표현",
        [
            "앱 설치", "어플 설치", "apk",
            "원격제어", "원격 지원",
            "첨부파일 실행", "프로그램 설치",
        ],
    ),
    (
        "당첨·환급·고수익을 미끼로 한 표현",
        [
            "당첨", "환급금", "지원금",
            "보상금", "고수익",
            "수익 보장", "무료 쿠폰",
        ],
    ),
    (
        "취업 또는 채용 관련 표현",
        [
            "채용", "구인", "구직",
            "인사담당자", "재택근무", "부업",
        ],
    ),
    (
        "기관 사칭 가능성",
        [
            "국세청", "검찰",
            "경찰", "금융감독원",
        ],
    ),
    (
        "도박 또는 투자 유도 표현",
        [
            "토토", "스포츠토토", "카지노",
            "배팅", "베팅", "적중",
            "고정픽", "당첨번호",
            "코인", "비트코인",
            "주식", "수익률",
            "트레이딩", "텔레그램",
        ],
    ),
    (
        "URL 또는 외부 접속 유도 표현",
        [
            "링크", "접속", "클릭",
            "바로가기", "확인하기",
            "조회하기", "인증하기",
            "로그인하기", "http", "https",
        ],
    ),
]


def extract_top_features(full_text: str) -> list:

    try:

        tfidf_union = model.named_steps["tfidf"]
        clf = model.named_steps["model"]

        x = tfidf_union.transform([full_text])

        feature_names = (
            tfidf_union.get_feature_names_out()
        )

        coef = clf.coef_[0]

        raw_features = []

        # 각 feature 기여도 계산
        for idx in x.nonzero()[1]:

            contribution = float(
                x[0, idx] * coef[idx]
            )

            feature_name = feature_names[idx]

            feature_name = feature_name.replace(
                "word_tfidf__",
                ""
            )

            feature_name = feature_name.replace(
                "char_tfidf__",
                ""
            )

            # 한 글자 제거
            if len(feature_name.strip()) < 2:
                continue

            # 기여도 너무 작으면 제거
            if abs(contribution) < 0.05:
                continue

            raw_features.append(
                {
                    "name": feature_name,
                    "contribution": round(
                        contribution,
                        4,
                    ),
                }
            )

        # 기여도 순 정렬
        raw_features = sorted(
            raw_features,
            key=lambda x: abs(
                x["contribution"]
            ),
            reverse=True,
        )

        filtered = []

        for feature in raw_features:

            name = feature["name"]

            duplicated = False

            for selected in filtered:

                selected_name = selected["name"]

                if (
                    name in selected_name
                    or selected_name in name
                ):
                    duplicated = True
                    break

            if duplicated:
                continue

            filtered.append(feature)

            # 상위 3개만
            if len(filtered) >= 3:
                break

        return filtered

    except Exception:
        return []
    

def analyze_email(
    text: str,
    subject: str | None = None,
) -> dict:

    try:

        if not text or not text.strip():

            return {
                "status": "error",
                "label": "unknown",
                "phishing_probability": None,
                "signals": [],
                "top_features": [],
                "model_version": "email-v1",
                "error": "empty_text",
            }

        full_text = f"{subject or ''} {text}"

        phishing_prob = float(
            model.predict_proba([full_text])[0][1]
        )

        label = (
            "phishing"
            if phishing_prob >= DEFAULT_THRESHOLD
            else "normal"
        )

        signals = []

        if label == "phishing":

            lowered_text = full_text.lower()

            for signal_name, keywords in SIGNAL_RULES:

                if any(
                    keyword.lower() in lowered_text
                    for keyword in keywords
                ):
                    signals.append(signal_name)

        top_features = extract_top_features(
            full_text
        )

        return {
            "status": "success",
            "label": label,
            "phishing_probability": round(
                phishing_prob,
                4,
            ),
            "signals": signals,
            "top_features": top_features,
            "model_version": "email-v1",
            "error": None,
        }

    except Exception:

        return {
            "status": "error",
            "label": "unknown",
            "phishing_probability": None,
            "signals": [],
            "top_features": [],
            "model_version": "email-v1",
            "error": "email analysis failed",
        }