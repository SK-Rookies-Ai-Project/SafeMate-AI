# SafeMate 모델–UI 연동 요구사항

## 1. 문서 목적

SMS·이메일 메시지 분류 모델과 URL 분석 모델의 결과를 SafeMate 분석 파이프라인과 Streamlit UI에서 동일한 형식으로 수신하고 시각화하기 위한 모델별 추론 계약을 정의한다.

전체 요청·응답과 검색 근거, 부분 실패 통합 방식은 `SafeMate_분석_통합_UI_공통계약.md`에서 정의한다.

## 2. 이메일·문자 메시지 분류 모델

### 2.1 추론 함수

```python
from typing import Literal


def analyze_message(
    text: str,
    input_type: Literal["sms", "email"],
    subject: str | None = None,
) -> dict:
    ...
```

### 2.2 입력

| 필드 | 타입 | 설명 |
|---|---|---|
| `text` | `str` | URL이 `[URL]`로 치환된 SMS 또는 이메일 본문 |
| `input_type` | `Literal["sms", "email"]` | UI와 파서에서 결정한 원본 메시지 유형 |
| `subject` | `str \| None` | 이메일 제목, SMS에서는 `None` |

### 2.3 성공 반환 계약

```python
{
    "status": "success",
    "label": "phishing",
    "phishing_probability": 0.84,
    "signals": [
        "개인정보 입력 요구",
        "긴급성을 강조하는 표현",
    ],
    "top_features": [
        {
            "name": "비밀번호",
            "value": 1.0,
            "contribution": 0.31,
        },
        {
            "name": "인증",
            "value": 1.0,
            "contribution": 0.26,
        },
    ],
    "model_version": "message-v1",
    "error": None,
}
```

### 2.4 필드 규칙

| 필드 | 필수 | 규칙 |
|---|---|---|
| `status` | 필수 | `success` 또는 `error` |
| `label` | 필수 | `normal`, `phishing`, `unknown` 중 하나 |
| `phishing_probability` | 필수 | `0.0`~`1.0`의 유한한 Python `float`, 판단 불가 시 `None` |
| `signals` | 필수 | 사람이 이해할 수 있는 위험 근거 목록 |
| `top_features` | 필수 | 판정에 영향을 준 단어와 기여도 목록, 계산 불가 시 빈 배열 |
| `model_version` | 필수 | 모델 또는 모델 파일 버전 |
| `error` | 필수 | 성공 시 `None`, 실패 시 안전한 오류 객체 |

`top_features`를 계산할 수 없는 모델은 임의 값을 생성하지 않고 빈 배열을 반환한다.

### 2.5 오류 반환 계약

```python
{
    "status": "error",
    "label": "unknown",
    "phishing_probability": None,
    "signals": [],
    "top_features": [],
    "model_version": "message-v1",
    "error": {
        "code": "MODEL_INFERENCE_FAILED",
        "message": "메시지를 분석하지 못했습니다.",
        "retryable": False,
    },
}
```

오류 객체에는 내부 스택트레이스, 파일 경로, 요청 원문 또는 민감정보를 포함하지 않는다.

### 2.6 입력 유형별 호출 예시

```python
# SMS
analyze_message(
    text="긴급 계정 인증이 필요합니다. [URL]",
    input_type="sms",
    subject=None,
)

# 이메일
analyze_message(
    text="계정 확인을 위해 [URL]에 접속하세요.",
    input_type="email",
    subject="계정 확인 안내",
)
```

### 2.7 운영 모델 선택 원칙

- `input_type`은 모델 종류가 아니라 원본 데이터 유형을 의미한다.
- UI는 이메일 전용 모델, SMS 전용 모델, 통합 모델을 직접 선택하지 않는다.
- UI와 분석 파이프라인은 `analyze_message()` 하나만 호출한다.
- 이메일·SMS 전용 모델을 라우팅할지 통합 모델 하나를 사용할지는 모델별 성능 비교 후 결정한다.
- 어떤 모델을 사용하더라도 함수 입력과 반환 계약은 동일하게 유지한다.
- 실제 사용 모델은 `model_version`으로 식별한다.

### 2.8 UI 사용 항목

- `phishing_probability`: 정상/피싱 확률 그래프
- `top_features`: 위험 단어 기여도 가로 막대그래프
- `signals`: 위험 신호 목록 또는 태그
- `model_version`: 분석에 사용한 모델 정보

### 2.9 납품 항목

- 추론 함수가 포함된 Python 모듈
- 학습 완료 모델 파일
- 전처리기 또는 토크나이저 파일
- 패키지와 버전이 명시된 requirements
- 정상 SMS, 피싱 SMS, 정상 이메일, 피싱 이메일, 오류 입력 테스트
- SMS와 이메일 단일 입력 실행 예제
- 이메일 전용·SMS 전용·통합 모델 중 서비스 적용 방식과 성능 비교 결과

## 3. URL 분석 모델

### 3.1 추론 함수

```python
def analyze_url(url: str) -> dict:
    ...
```

### 3.2 입력

| 필드 | 타입 | 설명 |
|---|---|---|
| `url` | `str` | 이메일 또는 문자에서 추출한 URL 원문 1개 |

### 3.3 성공 반환 계약

```python
{
    "status": "success",
    "url": "https://example.com/login",
    "label": "suspicious",
    "risk_score": 0.78,
    "signals": [
        "로그인 경로 포함",
        "URL 길이가 김",
        "특수문자 사용 비율이 높음",
    ],
    "features": [
        {
            "name": "URL 길이",
            "raw_value": 83,
            "normalized_value": 0.72,
            "contribution": 0.18,
        },
        {
            "name": "특수문자 개수",
            "raw_value": 7,
            "normalized_value": 0.61,
            "contribution": 0.14,
        },
    ],
    "model_version": "url-v1",
    "error": None,
}
```

### 3.4 필드 규칙

| 필드 | 필수 | 규칙 |
|---|---|---|
| `status` | 필수 | `success` 또는 `error` |
| `url` | 필수 | 입력받은 URL 원문과 정확히 동일한 값 |
| `label` | 필수 | `benign`, `suspicious`, `malicious`, `unknown` 중 하나 |
| `risk_score` | 필수 | `0.0`~`1.0`의 유한한 Python `float`, 판단 불가 시 `None` |
| `signals` | 필수 | 사람이 이해할 수 있는 URL 위험 근거 목록 |
| `features` | 필수 | 모델이 실제 사용한 URL 특징 목록, 설명값이 없으면 빈 배열 |
| `model_version` | 필수 | 모델 또는 모델 파일 버전 |
| `error` | 필수 | 성공 시 `None`, 실패 시 안전한 오류 객체 |

각 `features` 항목의 규칙:

| 필드 | 규칙 |
|---|---|
| `name` | UI에 표시할 특징명 |
| `raw_value` | JSON 호환 원본값(`str`, `int`, 유한한 `float`, `bool`, `None`) |
| `normalized_value` | 시각화용 `0.0`~`1.0` 유한한 Python `float` |
| `contribution` | 위험도 기여도, 계산 불가 시 `None` |

임의의 특징값이나 기여도를 생성하지 않는다. URL 분석은 문자열 특징만 사용하며 URL 접속이나 리디렉션 추적을 수행하지 않는다.

### 3.5 오류 반환 계약

```python
{
    "status": "error",
    "url": "invalid-url",
    "label": "unknown",
    "risk_score": None,
    "signals": [],
    "features": [],
    "model_version": "url-v1",
    "error": {
        "code": "INVALID_URL",
        "message": "URL을 분석하지 못했습니다.",
        "retryable": False,
    },
}
```

### 3.6 UI 사용 항목

- `risk_score`: URL 위험 점수 그래프
- `features[].normalized_value`: URL 특징별 가로 막대그래프
- `features[].contribution`: 특징별 위험 기여도 그래프
- `signals`: URL 구조와 위험 신호 목록

### 3.7 납품 항목

- 추론 함수가 포함된 Python 모듈
- 학습 완료 모델 파일
- 특징 추출기 또는 전처리기 파일
- 패키지와 버전이 명시된 requirements
- 정상 URL, 의심 URL, 잘못된 URL 테스트
- 단일 입력 실행 예제

## 4. 공통 연동 조건

1. UI는 모델 내부 구현이 아닌 `AnalysisClient`만 호출하고, 분석 파이프라인이 모델별 단일 추론 함수를 호출한다.
2. 추론 요청마다 모델을 재학습하지 않는다.
3. 모델과 전처리기는 최초 사용 시 한 번만 로드하거나 캐시한다.
4. 모든 반환값은 JSON 직렬화 가능한 Python `dict`로 구성한다.
5. NumPy scalar·array를 직접 반환하지 않고 `NaN`, `Infinity`, `-Infinity`를 반환하지 않는다.
6. 성공 결과는 `status="success"`, 실패 결과는 `status="error"`로 구분한다.
7. 실패 결과에 내부 스택트레이스, 파일 경로 또는 민감정보를 포함하지 않는다.
8. 계산할 수 없는 설명값과 기여도는 임의 생성하지 않고 빈 배열 또는 `None`으로 반환한다.
9. 모델 버전을 모든 결과에 포함한다.
10. Streamlit, Matplotlib, OpenAI API, Web Search, File Search 코드는 모델 모듈에 포함하지 않는다.
11. UI 시각화와 최종 사용자 설명은 SafeMate UI/분석 파이프라인에서 처리한다.
12. `input_type`은 `sms` 또는 `email` 데이터 유형만 표현하며 모델 종류를 표현하지 않는다.
13. 전용 모델 라우팅 또는 통합 모델 사용 여부와 관계없이 외부 추론 함수 계약을 유지한다.
14. URL 모델이 반환한 `url`이 입력값과 다르면 분석 파이프라인은 계약 오류로 처리한다.

## 5. 완료 기준

- 각 모델의 추론 함수를 별도 Python 코드에서 직접 호출할 수 있다.
- SMS, 이메일, URL 정상 입력과 오류 입력 모두 정의된 반환 계약을 따른다.
- 반환값을 `json.dumps(result, allow_nan=False)`로 직렬화할 수 있다.
- 모델 추론 과정에서 재학습 또는 외부 URL 접속이 발생하지 않는다.
- 테스트와 실행 예제로 연동 방법을 재현할 수 있다.
