"""
SMS 텍스트 전처리 공통 모듈.

TfidfVectorizer의 preprocessor 인자로 사용됨. 학습 스크립트
(train_and_export_model.py, train_experiments.py)와 추론 모듈(sms_model.py)이
전부 동일한 전처리를 거쳐야 하고, 특히 joblib으로 저장된 pkl을 나중에 다시
불러올 때 pickle이 이 함수를 모듈 경로로 참조하기 때문에 별도 파일로
분리해뒀다. sms_spam_model.pkl과 항상 같은 폴더에 이 파일도 있어야 한다.

배경: char n-gram(2~6) 벡터라이저에 URL을 그대로 넣으면 "http", "bit.ly"
같은 문자열이 "tt", "it", "tp:/"처럼 의미 없는 조각으로 쪼개져서, 모델
설명(top_features)에 노출됐을 때 사람이 읽기 어려운 문제가 있었다.
URL을 하나의 'url' placeholder 토큰으로 치환해서, 이 문제를 줄인다.

트레이드오프: 도메인명 자체(예: "복권천재.kr")가 가진 판별력은 사라지고
"URL이 있다/없다"는 정보만 남는다. 도메인 특이적 신호를 계속 쓰고 싶다면
치환 대신 도메인만 별도로 추출해 signals에 규칙으로 추가하는 방식을 고려.
"""

import re

_URL_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|\b[\w\-]+\.(?:com|co\.kr|kr|net|org|ly)(?:/\S*)?)",
    re.IGNORECASE,
)


def sms_preprocessor(text: str) -> str:
    """소문자 변환 + URL을 'url' placeholder로 치환.

    TfidfVectorizer(preprocessor=sms_preprocessor)로 넘기면 기본 소문자
    변환(lowercase=True)을 대체하므로, 여기서 직접 lower()를 호출해야 한다.
    """
    text = str(text).lower()
    text = _URL_PATTERN.sub(" url ", text)
    return text
