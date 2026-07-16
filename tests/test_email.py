import pickle

MODEL_PATH = "models/email_model.pkl"

with open(MODEL_PATH, "rb") as f:
    model = pickle.load(f)


SIGNAL_RULES = [
    (
        "개인정보 또는 인증정보 입력 요구",
        [
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
]


def analyze_email(
    text: str,
    subject: str | None = None,
) -> dict:

    try:

        full_text = f"{subject or ''} {text}"

        phishing_prob = float(
            model.predict_proba([full_text])[0][1]
        )

        label = (
            "phishing"
            if phishing_prob >= 0.5
            else "normal"
        )

        signals = []

        lowered_text = full_text.lower()

        for signal_name, keywords in SIGNAL_RULES:

            matched = any(
                keyword.lower() in lowered_text
                for keyword in keywords
            )

            if matched:
                signals.append(signal_name)

        return {
            "status": "success",
            "label": label,
            "phishing_probability": phishing_prob,
            "signals": signals,
            "top_features": [],
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