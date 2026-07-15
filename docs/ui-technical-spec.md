---
title: SafeMate AI Streamlit UI 기술명세서
created: 2026-07-14
updated: 2026-07-14
status: draft
owner: 이승현
team: 자비스
project: SafeMate AI
---

# SafeMate AI Streamlit UI 기술명세서

## 1. 문서 목적

SafeMate AI의 Streamlit UI 구현 구조, 공통 분석 파이프라인, 로컬 API 호출 계약, 상태 관리, 보안 및 테스트 기준을 정의한다. 모델 세부 구현과 일부 운영 값은 담당자 협의 후 확정한다.

## 2. MVP 아키텍처 결정

MVP는 Streamlit과 분석 코드를 같은 저장소와 실행 환경에서 구동한다. 별도 FastAPI 서버를 만들지 않고 `app.py`가 `src/pipeline.py`의 로컬 Python 인터페이스를 호출한다. 피싱·URL 모델은 OpenAI Responses API의 커스텀 도구로 등록하며, OpenAI가 반환한 Function Calling 요청에 따라 로컬에서 실행한다.

```text
Streamlit app.py
→ 입력 유형 선택(sms | email)
→ SMS 텍스트 정규화 또는 .eml 검증·파싱
→ URL 후보가 포함된 공통 AnalysisRequest 생성
→ src.pipeline.LocalAnalysisClient
→ OpenAI Responses API 호출(tools 등록)
→ OpenAI가 classify_message·analyze_urls Function Calling 요청
→ pipeline이 로컬 메시지·URL 모델 실행
→ function_call_output을 OpenAI에 반환
→ Web Search·File Search 및 최종 결과 종합
→ 표준 AnalysisResponse 반환
→ Streamlit 결과 렌더링
```


## 3. 프로젝트 구조

```text
SafeMate-AI/
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── .streamlit/
│   └── config.toml
├── src/
│   ├── config.py
│   ├── pipeline.py
│   ├── analyzers/
│   │   ├── input_parser.py
│   │   ├── text_analyzer.py
│   │   ├── url_analyzer.py
│   │   └── file_parser.py
│   ├── services/
│   │   ├── openai_client.py
│   │   ├── file_search.py
│   │   └── web_search.py
│   └── ui/
│       └── components.py
├── data/
│   ├── raw/
│   ├── processed/
│   ├── knowledge_base/
│   └── samples/
├── models/
├── tests/
├── scripts/
└── docs/
```

### 파일별 책임

| 경로 | 책임 |
|---|---|
| `app.py` | Streamlit 진입점, 화면 흐름, 세션 상태, 사용자 이벤트 |
| `src/config.py` | 환경변수, 파일 크기, URL 개수, 타임아웃 등 설정 |
| `src/pipeline.py` | 전체 분석 순서, 로컬 클라이언트 인터페이스, 결과 취합 |
| `src/analyzers/input_parser.py` | SMS 공백·10,000자 검증, 텍스트 정규화와 URL 후보 추출 |
| `src/analyzers/file_parser.py` | `.eml` 검증·파싱, 텍스트 URL 및 HTML `href`·외부 이미지 `src` 후보 추출 |
| `src/analyzers/text_analyzer.py` | `input_type`에 따른 문자·이메일 피싱 모델 입력 구성 및 호출 |
| `src/analyzers/url_analyzer.py` | URL 재검증·중복 제거·URL별 모델 호출 |
| `src/services/openai_client.py` | OpenAI Responses API와 Function Calling 연동 |
| `src/services/web_search.py` | 최신 위협 사례 검색과 Web 근거 정규화 |
| `src/services/file_search.py` | 공식 지침 검색과 File 근거 정규화 |
| `src/ui/components.py` | 입력 유형 선택, SMS 입력, 이메일 업로드, 미리보기, 결과 카드, 오류 UI 구성요소 |
| `src/ui/visualizations.py` | 모델 반환 계약을 Matplotlib 확률·특징·기여도 그래프로 변환 |
| `data/knowledge_base/` | File Search에 사용할 검수된 공식 자료 |
| `data/samples/` | 개인정보가 제거된 정상·위험 SMS 및 이메일 데모 입력 |
| `models/` | 학습된 모델과 전처리기 파일 |
| `tests/` | 파서, 분석기, 파이프라인, UI 테스트 |

### 분석 후 후속 채팅 경계

- 후속 채팅은 `analysis_status`가 성공이고 `analysis_result`가 존재할 때만 노출한다.
- 1차 분류 입력에는 사용자의 채팅 질문을 포함하지 않는다.
- LLM에는 허용 목록으로 선택한 분석 결과 필드만 JSON 스냅샷으로 전달한다.
- Web Search는 기본 제공하고 `OPENAI_VECTOR_STORE_ID`가 있을 때만 File Search를 추가한다.
- 대화 기록은 Streamlit 세션에만 유지하고 Responses API는 `store: false`로 호출한다.
- 입력 해시 변경, 재분석, 입력 유형 변경 또는 초기화 시 채팅 상태를 제거한다.

### 분석 결과 시각화 경계

- 메시지 확률 그래프는 `phishing_probability`만 사용하며 정상 확률은 `1 - phishing_probability`로 표시한다.
- 메시지 특징 그래프는 `top_features[].contribution`이 있는 항목만 표시한다.
- URL 비교 그래프는 `url_analysis[].risk_score`, 특징 그래프는 `features[].normalized_value`를 사용한다.
- URL 기여도 그래프는 `features[].contribution`이 `None`이 아닌 항목만 표시한다.
- 누락되거나 범위를 벗어난 값을 임의로 보정하거나 생성하지 않는다.

`data/raw/`에는 학습용 원천 데이터만 저장하며 사용자가 입력한 SMS와 업로드한 이메일은 저장하지 않는다. 비밀정보와 모델 대용량 파일의 Git 추적 여부는 `.gitignore`에서 관리한다.

## 4. 담당 경계

### Streamlit UI 및 공통 파이프라인

- 사용자가 `sms` 또는 `email` 중 하나의 입력 유형을 선택하도록 한다.
- `sms`는 사용자가 SMS 원문을 URL까지 포함하여 `st.text_area`에 붙여넣는다.
- `email`은 `.eml` 확장자, 최대 25MB 크기 및 실제 이메일 구조를 검증한 뒤 자동 파싱한다.
- 두 입력을 동시에 사용하지 않으며 입력 유형 변경 시 기존 미리보기와 분석 결과를 초기화한다.
- SMS 본문 또는 이메일의 디코딩된 텍스트와 HTML `href`·외부 이미지 `src`에서 URL을 추출한다.
- 본문 내 URL을 `[URL]`로 치환하고 URL 후보 메타데이터를 보존한 공통 `AnalysisRequest`를 생성한다.
- UI는 TF-IDF 변환이나 URL 특징 추출을 직접 수행하지 않는다.
- 통합 로딩과 성공·부분 성공·실패 결과를 표시한다.

### 분석 API 서비스

- `input_type`, 제목, 필터링된 본문과 URL 후보 재검증
- OpenAI Responses API에 `classify_message`와 `analyze_urls` 커스텀 도구 등록
- OpenAI의 Function Calling 요청 수신 및 로컬 모델 실행
- `url_analyzer.py`에서 URL 재검증·중복 제거·우선순위·20개 제한을 한 번만 적용
- 도구 실행 결과를 `function_call_output`으로 OpenAI에 반환
- Web Search·File Search 실행
- LLM 결과 종합 및 표준 응답 생성

## 5. 전체 데이터 흐름

```text
[sms 입력]
SMS 원문 붙여넣기
→ 공백·10,000자 검증
→ input_type을 sms로 설정
→ 텍스트 정규식으로 URL 후보 추출
→ 본문 내 URL을 [URL]로 치환

[email 입력]
.eml 업로드
→ 확장자·크기·내용·이메일 구조 검증
→ 안전한 이메일 자동 파싱
→ input_type을 email로 설정
→ 발신자·제목·텍스트 본문 추출
→ 텍스트와 HTML href·외부 이미지 src에서 URL 후보 추출
→ 본문 내 URL을 [URL]로 치환

[공통 처리]
→ input_type, subject, 필터링된 body, url_candidates로 AnalysisRequest 생성
→ LocalAnalysisClient가 OpenAI Responses API 호출
→ OpenAI가 classify_message 또는 analyze_urls 도구 호출 요청
→ classify_message는 문자·이메일 모델 실행
→ analyze_urls는 URL 후보를 재검증·중복 제거하고 최대 20개 선택 후 URL별 모델 실행
→ function_call_output을 OpenAI에 반환
→ Web Search·File Search·LLM 결과 취합
→ AnalysisResponse 검증
→ Streamlit 결과 렌더링
```

## 6. Streamlit 구성요소

| 목적 | Streamlit 구성요소 |
|---|---|
| 페이지 설정 | `st.set_page_config` |
| 입력 유형 선택 | `st.radio(options=["sms", "email"], horizontal=True)` |
| SMS 직접 입력 | `st.text_area(max_chars=MAX_SMS_CHARS)` |
| 이메일 업로드 | `st.file_uploader(type=["eml"])` |
| 입력 미리보기 | `st.container`, `st.text_input`, `st.text_area` |
| 의심 URL 표시 | `st.code`, 일반 텍스트 |
| 분석 실행 | `st.button` |
| 통합 로딩 | `st.spinner` 또는 `st.status` |
| 핵심 결과 | `st.metric`, `st.container` |
| 상세 결과 | `st.tabs`, `st.expander` |
| 오류 안내 | `st.error`, `st.warning`, `st.info` |
| 상태 관리 | `st.session_state` |

API가 단계별 상태를 제공하지 않는 MVP에서는 `이메일 분석 → URL 분석 → 검색`과 같은 추정 진행률을 표시하지 않는다. 요청 중에는 `입력 내용을 분석하고 있습니다.`라는 통합 로딩 상태만 표시한다.

## 7. 세션 상태와 파일 변경 감지

```python
DEFAULT_STATE = {
    "input_type": "sms",
    "sms_text": "",
    "uploaded_file_name": None,
    "uploaded_file_digest": None,
    "current_input_digest": None,
    "last_analyzed_digest": None,
    "parsed_email": None,
    "url_candidates": [],
    "analysis_status": "idle",
    "analysis_result": None,
    "analysis_error": None,
    "uploader_key": 0,
}
```

### 상태 값

- `idle`: SMS 미입력 또는 이메일 파일 미선택
- `ready`: 선택한 입력의 검증과 미리보기 완료
- `analyzing`: 분석 진행 중
- `success`: 필수 분석 완료
- `partial_success`: 일부 URL 또는 검색 기능 실패
- `error`: 핵심 결과 제공 불가

입력 유형과 내용을 함께 해시하여 동일한 분석 요청인지 판단한다. 이메일은 파일 바이트, SMS는 정규화된 텍스트를 사용한다.

```python
import hashlib


def create_input_digest(input_type: str, content: bytes) -> str:
    return hashlib.sha256(input_type.encode() + b":" + content).hexdigest()


email_digest = create_input_digest("email", file_bytes)
sms_digest = create_input_digest("sms", sms_text.strip().encode("utf-8"))
```

입력 유형이나 해시가 변경되면 이전 미리보기와 분석 결과를 제거한다. `last_analyzed_digest`가 현재 입력 해시와 같고 사용자가 재분석을 명시적으로 요청하지 않았다면 자동 재호출하지 않는다.

### 초기화

```python
uploaded_file = st.file_uploader(
    "이메일 파일",
    type=["eml"],
    key=f"eml_uploader_{st.session_state.uploader_key}",
)
```

초기화 버튼을 누르면 분석 관련 상태를 기본값으로 되돌린 뒤 다음을 실행한다.

```python
st.session_state.uploader_key += 1
st.rerun()
```

## 8. 문자 메시지 직접 입력

SMS 입력은 사용자가 받은 문자 내용을 URL까지 포함하여 그대로 복사·붙여넣는 방식으로 제공한다. 한 줄 입력이 아니라 줄바꿈과 긴 내용을 지원해야 하므로 `st.text_area`를 사용한다.

```python
MAX_SMS_CHARS = 10_000

sms_text = st.text_area(
    "받은 문자 내용을 붙여넣어 주세요.",
    placeholder="문자 내용을 URL까지 포함하여 그대로 붙여넣어 주세요.",
    height=200,
    max_chars=MAX_SMS_CHARS,
)
```

### SMS 입력 정규화

```python
def prepare_sms_input(raw_text: str) -> dict:
    normalized_text = raw_text.strip()

    if not normalized_text:
        raise ValueError("분석할 문자 내용을 입력해 주세요.")

    if len(normalized_text) > MAX_SMS_CHARS:
        raise ValueError("문자 내용이 최대 입력 길이를 초과했습니다.")

    url_candidates = extract_text_url_candidates(normalized_text)
    filtered_body = replace_urls(normalized_text, replacement="[URL]")

    return {
        "input_type": "sms",
        "preview": {
            "body": normalized_text,
            "url_candidates": url_candidates,
        },
        "subject": None,
        "body": filtered_body,
        "url_candidates": url_candidates,
    }
```

### 처리 규칙

- SMS와 `.eml`은 동시에 입력하지 않으며 사용자가 입력 유형 중 하나를 선택한다.
- 입력 유형을 변경하면 기존 입력, URL 목록과 분석 결과를 초기화한다.
- 공백만 있는 입력과 10,000자를 초과한 입력은 분석하지 않는다.
- 붙여넣은 원문은 미리보기에만 사용하며 모델 입력에서는 URL을 `[URL]`로 치환한다.
- URL 후보 원문과 출처 유형은 `AnalysisRequest`에 보존하며 UI에서는 클릭 불가능하게 표시한다.
- SMS 원문을 Markdown이나 HTML로 해석하지 않고 일반 텍스트로 표시한다.
- SMS 원문을 파일이나 로그에 저장하지 않는다.

## 9. `.eml` 파일 처리

`src/analyzers/file_parser.py`에서 Python 표준 라이브러리 `email`을 사용한다.

### 검증 설계 근거

파일 검증은 `PBL01-2`의 확장자 위장 탐지, 파일 앞부분 바이트 확인, 확장자와 실제 내용 비교 방식을 참고한다. 다만 `.eml`은 PDF·PNG처럼 고정된 매직 바이트가 없는 텍스트 기반 이메일 형식이므로, 매직 바이트만으로 유효성을 판정하지 않는다.

- 파일명과 확장자는 사용자가 변경할 수 있으므로 `st.file_uploader(type=["eml"])`의 결과만 신뢰하지 않는다.
- 알려진 PDF·ZIP·이미지·실행 파일 시그니처는 명백한 확장자 위장 탐지에 사용한다.
- 바이너리 시그니처가 없더라도 일반 텍스트 파일을 `.eml`로 바꾼 경우가 있으므로 Python `email` 모듈로 실제 파싱한다.
- `BytesParser`는 일부 일반 텍스트도 본문으로 허용할 수 있으므로 파싱 성공 여부뿐 아니라 이메일 헤더와 제목·본문 구조를 추가로 검증한다.
- 이 검증은 과제 범위의 방어적 입력 검증이며 전문 파일 포렌식이나 악성코드 탐지를 대체하지 않는다.

### 검증 순서

```text
파일 업로드
→ 마지막 확장자가 .eml인지 확인
→ 의심스러운 이중 확장자 확인
→ 빈 파일·파일 크기 확인
→ 알려진 바이너리 시그니처 확인
→ BytesParser로 이메일 파싱
→ 이메일 헤더 존재 여부 확인
→ 제목 또는 본문 존재 여부 확인
→ MIME 본문을 안전한 텍스트로 추출
→ 미리보기와 AnalysisRequest 생성
```

### 확장자 및 내용 검증 예시

```python
from email import policy
from email.parser import BytesParser
from pathlib import Path


MAX_EML_SIZE_BYTES = 25 * 1024 * 1024
MAX_URLS_TO_ANALYZE = 20

SUSPICIOUS_PREVIOUS_EXTENSIONS = {
    ".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif",
    ".exe", ".class", ".py", ".js",
}

KNOWN_BINARY_SIGNATURES = (
    (b"%PDF", "PDF"),
    (b"PK\x03\x04", "ZIP"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"\xca\xfe\xba\xbe", "Java class"),
    (b"MZ", "Windows executable"),
)

RECOGNIZED_EMAIL_HEADERS = (
    "From", "To", "Subject", "Date", "Message-ID",
)


class EmlValidationError(ValueError):
    pass


def validate_eml(filename: str, file_bytes: bytes):
    extensions = [suffix.lower() for suffix in Path(filename).suffixes]

    if not extensions or extensions[-1] != ".eml":
        raise EmlValidationError(".eml 파일만 업로드할 수 있습니다.")

    if len(extensions) >= 2 and extensions[-2] in SUSPICIOUS_PREVIOUS_EXTENSIONS:
        raise EmlValidationError("이중 확장자가 의심되는 파일입니다.")

    if not file_bytes:
        raise EmlValidationError("파일 내용이 비어 있습니다.")

    if len(file_bytes) > MAX_EML_SIZE_BYTES:
        raise EmlValidationError("파일 크기는 25MB 이하여야 합니다.")

    sample = file_bytes[:4096].lstrip()
    for signature, detected_type in KNOWN_BINARY_SIGNATURES:
        if sample.startswith(signature):
            raise EmlValidationError(
                f"확장자는 .eml이지만 실제 내용은 {detected_type} 파일로 추정됩니다."
            )

    try:
        message = BytesParser(policy=policy.default).parsebytes(file_bytes)
    except Exception as exc:
        raise EmlValidationError("이메일 형식을 파싱할 수 없습니다.") from exc

    if not any(message.get(header) for header in RECOGNIZED_EMAIL_HEADERS):
        raise EmlValidationError("유효한 이메일 헤더를 찾을 수 없습니다.")

    body = extract_text_body(message).strip()
    subject = str(message.get("Subject", "")).strip()

    if not subject and not body:
        raise EmlValidationError("이메일 제목과 본문을 찾을 수 없습니다.")

    parse_warnings = [
        type(defect).__name__
        for part in message.walk()
        for defect in part.defects
    ]
    return message, parse_warnings
```

파싱 결함(`message.defects`)은 무조건 차단하지 않고 경고 정보로 수집한다. 오래된 이메일이나 비표준 MIME 이메일도 일부 결함을 포함할 수 있기 때문이다. 필수 이메일 헤더가 없거나 제목과 본문을 모두 읽을 수 없는 경우에는 분석을 중단한다.

### 파싱 및 분석 요청 데이터 생성

```python
def parse_eml(file_bytes: bytes, filename: str) -> dict:
    message, parse_warnings = validate_eml(filename, file_bytes)
    original_body = extract_text_body(message)
    subject = str(message.get("Subject", "")).strip()
    url_candidates = extract_url_candidates(message)
    filtered_body = replace_urls(original_body, replacement="[URL]")

    return {
        "input_type": "email",
        "preview": {
            "from": str(message.get("From", "")),
            "to": str(message.get("To", "")),
            "subject": subject,
            "body": original_body,
            "url_candidates": url_candidates,
        },
        "subject": subject,
        "body": filtered_body,
        "url_candidates": url_candidates,
        "parse_warnings": parse_warnings,
    }
```

### 처리 규칙

- 파일명 확장자는 대소문자를 구분하지 않고 검사하며 `.EML`도 허용한다.
- `invoice.pdf.eml`처럼 바로 앞 확장자가 문서·압축·이미지·실행 파일 형식이면 이중 확장자 위장으로 차단한다.
- 파일 크기는 Gmail 첨부 기준을 적용하여 최대 25MB로 제한한다.
- `MAX_EML_SIZE_BYTES = 25 * 1024 * 1024`를 `src/config.py`에서 관리한다.
- MIME 멀티파트에서는 `text/plain`을 우선 사용한다.
- `text/plain`이 없으면 HTML에서 텍스트만 추출한다.
- HTML 본문을 `st.markdown(..., unsafe_allow_html=True)`로 렌더링하지 않는다.
- `script`, `iframe`, `form`, `img`와 외부 리소스를 로드하지 않는다.
- HTML의 `a[href]`와 외부 `img[src]` 값은 파싱만 하며 해당 URL이나 이미지를 요청하지 않는다.
- `cid:`와 `data:` URL은 외부 URL 분석 대상에서 제외한다.
- 첨부파일을 자동 실행하거나 열지 않는다.
- 파싱 완료 후 URL 분리와 분석 요청 데이터 생성을 자동 수행한다.
- 사용자 업로드 파일과 이메일 원문을 저장하거나 로그에 기록하지 않는다.

## 10. URL 처리

### 호출 방식

```text
input_parser.py: SMS 일반 텍스트에서 URL 후보 추출
file_parser.py: 이메일 텍스트·HTML에서 URL 후보 추출
→ pipeline.py: 후보의 `url`, `source_type`, `input_index` 보존
→ url_analyzer.py: 형식 재검증 및 최초 등장 순서 기준 중복 제거
→ 사용자 클릭 대상인 `text`·`href`를 `image_src`보다 우선하여 최대 20개 선택
→ URL별 analyze_url(url) 반복 호출
→ URL별 성공·실패와 제외 개수 취합
```

### 확정 규칙

- URL 후보 선택·중복 제거·20개 제한은 `url_analyzer.py`에서만 수행한다.
- 최초 등장 순서를 기준으로 중복 제거한다.
- 사용자 클릭 대상인 일반 텍스트 URL과 `href`를 이미지 `src`보다 우선한다.
- 기본 최대 분석 개수는 20개이며 `MAX_URLS_TO_ANALYZE` 설정으로 변경할 수 있다.
- 제한을 초과하면 `omitted_url_count`로 제외 개수를 반환한다.
- `cid:`와 `data:` URL은 제외한다.
- URL 하나의 실패가 전체 요청을 중단하지 않는다.
- 실제 URL이나 이미지를 요청하지 않고 문자열 특징만 분석한다.
- SMS와 이메일에서 추출된 URL은 클릭 불가능한 텍스트로 표시한다.

URL 후보의 내부 형식:

```json
{
  "url": "https://example.com",
  "source_type": "href",
  "input_index": 0
}
```

HTML 링크의 표시 텍스트에 URL이 포함된 경우 다음 메타데이터를 추가한다.

```json
{
  "url": "https://evil.example/login",
  "source_type": "href",
  "input_index": 0,
  "displayed_url": "https://official.example/login",
  "displayed_domain": "official.example",
  "destination_domain": "evil.example",
  "display_href_mismatch": true,
  "signals": ["표시 주소와 실제 연결 도메인이 다릅니다."]
}
```

- 비교를 위해 호스트를 소문자·IDNA ASCII 형태로 정규화하고 선행 `www.`를 제거한다.
- 한쪽 도메인이 다른 쪽의 정상적인 하위 도메인이면 같은 도메인 계열로 처리한다.
- 상대경로와 `javascript:`, `mailto:`, `data:`, `cid:` 링크는 외부 URL 후보로 만들지 않는다.
- 이 검사는 URL에 접속하거나 리디렉션을 따라가지 않는 정적 문자열 검사다.
반환 항목에는 원본 위치 정보를 포함한다.

```json
{
  "url": "https://example.com",
  "input_indexes": [0, 2],
  "occurrence_count": 2,
  "source_types": ["text", "href"],
  "status": "success",
  "label": "suspicious",
  "risk_score": 0.78
}
```

## 11. 로컬 분석 인터페이스

`src/pipeline.py`에 UI가 의존할 인터페이스를 정의한다.

```python
class AnalysisClient:
    def analyze(self, payload: "AnalysisRequest") -> "AnalysisResponse":
        raise NotImplementedError


class LocalAnalysisClient(AnalysisClient):
    def analyze(self, payload: "AnalysisRequest") -> "AnalysisResponse":
        # input_type에 따라 공통 분석기와 OpenAI 서비스를 호출한다.
        ...


class MockAnalysisClient(AnalysisClient):
    def analyze(self, payload: "AnalysisRequest") -> "AnalysisResponse":
        return MOCK_ANALYSIS_RESULT
```

`app.py`는 실제 분석 과정이나 Mock 분기를 직접 구현하지 않고 `AnalysisClient`만 호출한다.

## 12. 모델 호출 및 데이터 형식 계약

### 계층별 전달 형식

같은 Python 프로세스에서 동작하므로 UI와 pipeline 사이는 JSON 문자열이 아닌 JSON 호환 Python `dict` 또는 dataclass를 사용한다. OpenAI Function Calling의 도구 인자와 결과는 JSON 스키마로 검증한다.

```text
Streamlit → pipeline
구조화된 AnalysisRequest

pipeline → OpenAI Responses API
AnalysisRequest + classify_message/analyze_urls 도구 스키마

OpenAI → pipeline
function_call(name, arguments)

pipeline → 로컬 모델
검증된 명시적 Python 인자

pipeline → OpenAI
function_call_output(JSON 호환 모델 결과)

OpenAI → pipeline
Web/File Search를 포함한 최종 AnalysisResponse
```

다음과 같은 자유 형식 문자열을 ML 모델 호출 계약으로 사용하지 않는다.

```text
입력 유형: SMS
본문: 지원 결과를 확인하세요.
URL: https://example.com
```

### 메시지 분류 모델 인터페이스

```python
from typing import Literal


def analyze_message(
    text: str,
    input_type: Literal["sms", "email"],
    subject: str | None = None,
) -> dict:
    ...
```

- `text`에는 URL을 `[URL]`로 치환한 SMS 또는 이메일 본문을 전달한다.
- `subject`는 이메일일 때만 사용하며 SMS에서는 `None`이다.
- UI와 pipeline은 TF-IDF 벡터를 생성하지 않는다.
- 모델팀은 학습 때 사용한 동일한 전처리기와 `TfidfVectorizer`를 모델과 함께 로드하고 함수 내부에서 `transform([text])`을 수행한다.
- 추론 시 `TfidfVectorizer.fit()` 또는 `fit_transform()`을 다시 실행하지 않는다.
- SMS와 이메일을 하나의 모델로 처리할지 입력 유형별 모델로 라우팅할지는 모델팀이 결정하되 외부 함수 계약은 동일하게 유지한다.

권장 반환 형식:

```json
{
  "status": "success",
  "label": "phishing",
  "phishing_probability": 0.91,
  "signals": ["개인정보 제출 요구"],
  "model_version": "message-v1",
  "error": null
}
```

### URL 분석 모델 인터페이스

```python
def analyze_url(url: str) -> dict:
    ...
```

- URL 분석기에는 추출된 URL 원문 하나를 문자열로 전달한다.
- UI는 URL 길이, 특수문자 수, 도메인 구조 등 모델 특징을 직접 계산하지 않는다.
- URL 모델팀이 학습 때 사용한 특징 추출기를 함수 내부에서 동일하게 적용한다.
- pipeline은 URL별로 함수를 호출하고 하나의 실패가 다른 URL 분석을 중단하지 않도록 결과를 취합한다.
- URL 분석 함수는 실제 URL에 네트워크 요청을 보내지 않는다.

권장 반환 형식:

```json
{
  "status": "success",
  "url": "https://example.com",
  "label": "suspicious",
  "risk_score": 0.78,
  "signals": ["로그인 유도 키워드"],
  "model_version": "url-v1",
  "error": null
}
```

### OpenAI Function Calling 도구 계약

`classify_message` 도구:

```json
{
  "type": "function",
  "name": "classify_message",
  "description": "SMS 또는 이메일 본문의 피싱 가능성을 분류합니다.",
  "strict": true,
  "parameters": {
    "type": "object",
    "properties": {
      "input_type": {
        "type": "string",
        "enum": ["sms", "email"]
      },
      "subject": {
        "type": ["string", "null"]
      },
      "body": {
        "type": "string"
      }
    },
    "required": ["input_type", "subject", "body"],
    "additionalProperties": false
  }
}
```

`analyze_urls` 도구:

```json
{
  "type": "function",
  "name": "analyze_urls",
  "description": "추출된 URL 후보를 검증하고 URL별 위험도를 분석합니다.",
  "strict": true,
  "parameters": {
    "type": "object",
    "properties": {
      "url_candidates": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "url": {"type": "string"},
            "source_type": {
              "type": "string",
              "enum": ["text", "href", "image_src"]
            },
            "input_index": {"type": "integer", "minimum": 0}
          },
          "required": ["url", "source_type", "input_index"],
          "additionalProperties": false
        }
      }
    },
    "required": ["url_candidates"],
    "additionalProperties": false
  }
}
```

Function Calling 실행 규칙:

1. 도구 인자는 원본 `AnalysisRequest`와 대조하여 URL 추가·변조 여부를 차단한다.
2. `classify_message`는 로컬 `analyze_message()`를 호출한다.
3. `analyze_urls`는 `url_analyzer.py`에서 후보를 재검증·중복 제거·우선순위화한 뒤 최대 20개를 `analyze_url()`에 전달한다.
4. 각 실행 결과는 JSON 직렬화 가능한 객체로 `function_call_output`에 반환한다.
5. 도구 호출이 여러 개면 모두 처리한 후 최종 응답 생성을 요청한다.

### OpenAI 전달 형식

pipeline은 메시지 모델과 URL 모델의 구조화된 결과를 JSON 호환 객체로 OpenAI 서비스에 전달한다. 모델 결과를 임의의 자연어 목록으로 합쳐 유일한 계약으로 사용하지 않는다. Function Calling 결과, Web Search와 File Search 결과도 동일한 `AnalysisResponse` 스키마로 정규화한다.

## 13. 요청 스키마

SMS와 이메일을 공통 `AnalysisRequest` 구조로 정규화한다. `subject`는 이메일에서만 문자열 값을 가지며 SMS에서는 `null`이다. `body`는 URL을 `[URL]`로 치환한 모델 입력용 본문이고, URL 원문과 출처는 `url_candidates` 배열에 보존한다.

### SMS 요청 예시

```json
{
  "schema_version": "1.0",
  "request_id": "analysis-20260714-001",
  "input_type": "sms",
  "subject": null,
  "body": "지원 결과를 확인하려면 다음 주소에 접속하세요. [URL]",
  "url_candidates": [
    {
      "url": "https://example.com/register",
      "source_type": "text",
      "input_index": 0
    }
  ]
}
```

### 이메일 요청 예시

```json
{
  "schema_version": "1.0",
  "request_id": "analysis-20260714-002",
  "input_type": "email",
  "subject": "최종 합격 및 계정 확인 안내",
  "body": "계정 확인을 위해 다음 주소에 접속하세요. [URL]",
  "url_candidates": [
    {
      "url": "https://example.com/register",
      "source_type": "href",
      "input_index": 0
    }
  ]
}
```

이메일의 발신자와 수신자는 Streamlit 미리보기에 사용하며 메시지 모델팀이 필요하다고 합의한 경우에만 추후 요청 스키마에 추가한다.

### 요청 전 검증

- 지원하는 `schema_version`인지 확인
- `input_type`이 `sms` 또는 `email`인지 확인
- `sms`이면 공백을 제외한 본문이 존재하고 최대 10,000자 이하인지 확인
- `email`이면 `.eml` 확장자, 25MB 이하 크기, 내용 유형과 이메일 구조 검증을 통과했는지 확인
- `email`이면 `subject`가 문자열 또는 `null`인지 확인하고 `sms`이면 `subject`가 `null`인지 확인
- 필터링된 본문 존재 여부
- 추출된 URL이 본문에서 `[URL]`로 치환되었는지 확인
- `url_candidates` 각 항목의 URL·출처 유형·원본 위치 형식
- 요청 본문 크기

## 14. 응답 스키마

```json
{
  "schema_version": "1.0",
  "request_id": "analysis-20260714-002",
  "input_type": "email",
  "status": "partial_success",
  "overall_risk": {
    "level": "high",
    "score": 0.87
  },
  "summary": "개인정보 제출 요구와 의심스러운 URL이 확인되었습니다.",
  "risk_reasons": [
    "개인정보 제출 요구",
    "긴급한 행동 유도"
  ],
  "recommended_actions": [
    "이메일 속 링크를 열지 마세요.",
    "기업 공식 채용 페이지에서 사실 여부를 확인하세요."
  ],
  "message_analysis": {
    "status": "success",
    "label": "phishing",
    "phishing_probability": 0.91,
    "signals": ["개인정보 제출 요구"],
    "model_version": "message-v1"
  },
  "url_analysis_summary": {
    "candidate_count": 24,
    "analyzed_count": 20,
    "omitted_url_count": 4
  },
  "url_analysis": [
    {
      "url": "https://example.com/register",
      "input_indexes": [0],
      "occurrence_count": 1,
      "source_types": ["href"],
      "status": "success",
      "label": "suspicious",
      "risk_score": 0.78,
      "signals": ["로그인 유도 키워드"],
      "model_version": "url-v1",
      "error": null
    }
  ],
  "web_evidence": [
    {
      "evidence_id": "WEB-001",
      "title": "채용 사칭 피싱 주의 안내",
      "organization": "한국인터넷진흥원",
      "published_at": "2026-06-01",
      "retrieved_at": "2026-07-14T09:30:00+09:00",
      "url": "https://example.go.kr/security-notice",
      "summary": "채용을 사칭해 개인정보 입력을 요구하는 사례",
      "citation_type": "web"
    }
  ],
  "file_evidence": [
    {
      "evidence_id": "FILE-001",
      "title": "피싱 대응 지침",
      "organization": "한국인터넷진흥원",
      "filename": "phishing_guideline.pdf",
      "page": 12,
      "excerpt": "의심스러운 링크를 클릭하지 않습니다.",
      "external_url": null,
      "citation_type": "file"
    }
  ],
  "limitations": [
    {
      "code": "MODEL_NOT_DETERMINISTIC",
      "message": "분석 결과만으로 실제 피싱 여부를 확정할 수 없습니다."
    }
  ],
  "errors": [
    {
      "component": "web_search",
      "code": "SEARCH_TIMEOUT",
      "message": "최신 사례 검색 시간이 초과되었습니다.",
      "retryable": true
    }
  ]
}
```

### 상태와 점수 정의

- `status`: `success`, `partial_success`, `error` 중 하나
- `overall_risk.level`: `low`, `medium`, `high`, `unknown` 중 하나
- 모든 점수 범위는 `0.0` 이상 `1.0` 이하
- `phishing_probability`: 피싱 클래스 예측 확률
- `risk_score`: URL 위험도를 정규화한 점수
- `overall_risk.score`: API가 모델·규칙·검색 결과를 종합한 점수
- UI는 점수를 재계산하거나 임의로 보정하지 않는다.
- UI는 지원하지 않는 `schema_version`을 받으면 결과를 렌더링하지 않고 안전한 오류를 표시한다.

## 15. UI 렌더링 규칙

### 종합 결과

- 위험 수준, 요약, 위험 근거, 권장 행동 순으로 표시한다.
- 색상만으로 위험 수준을 표현하지 않는다.
- 위험 근거는 최대 5개, 각 100자 이내로 표시한다.
- 권장 행동은 우선순위 순으로 최대 5개 표시한다.

### 상세 탭

1. 문자·이메일 분석
2. URL 분석
3. 공식 출처
4. 분석 한계

### 링크 구분

- SMS와 이메일에서 추출된 의심 URL은 `st.code` 또는 일반 텍스트로 표시하며 클릭을 허용하지 않는다.
- Web Search 공식 출처는 `http/https` 스킴과 허용 도메인을 검증한 후 기관명·도메인과 함께 클릭 가능한 링크로 표시한다.
- File Search 출처는 파일명, 문서 제목, 페이지 또는 인용 위치를 표시한다.
- File Search에 외부 URL이 있는 경우 동일한 URL 검증을 통과한 링크만 표시한다.
- 링크를 새 창에서 여는 동작은 안전한 HTML 사용 여부를 검토하여 구현하며, 검증되지 않은 HTML을 렌더링하지 않는다.

## 16. 오류 처리

| 오류 | UI 처리 |
|---|---|
| SMS 입력 없음 | 분석 버튼 비활성화 및 입력 안내 |
| SMS 최대 길이 초과 | 입력 길이 안내 및 분석 차단 |
| 파일 형식 오류 | 분석 버튼 비활성화 및 형식 안내 |
| `.eml` 파싱 실패 | 파일 재선택 안내 |
| 확장자·실제 내용 불일치 | 위장 가능성을 안내하고 분석 차단 |
| URL 없음 | SMS 또는 이메일 본문 분석은 계속 진행 |
| 요청 시간 초과 | 입력 유지, 재시도 및 초기화 제공 |
| 인증 실패 | API 키와 내부 응답을 숨기고 서비스 오류 표시 |
| 문자·이메일 모델 실패 | 가능한 URL·검색 결과 표시 |
| URL 일부 실패 | 성공 결과 유지, URL별 오류 표시 |
| Web/File Search 실패 | 모델 결과 유지, 검색 실패 안내 |
| 스키마 버전 불일치 | 결과를 렌더링하지 않고 호환성 오류 표시 |
| 응답 스키마 오류 | 내부 원문을 숨기고 일반 오류 표시 |

화면과 일반 로그에는 내부 예외 메시지, API 응답 원문, SMS·이메일 원문, 개인정보, API 키 및 전체 의심 URL을 기록하지 않는다.

## 17. 보안 및 데이터 처리

- API 키는 `.env` 또는 `st.secrets`로 관리한다.
- `.env`는 Git에 포함하지 않고 `.env.example`에는 키 이름만 기록한다.
- 입력한 SMS, 업로드 이메일과 분석 결과를 영구 저장하지 않는다.
- 입력한 SMS와 업로드한 이메일 내용이 분석 과정에서 OpenAI API로 전송될 수 있음을 사용자에게 안내한다.
- 실제 개인정보, 비밀번호, 계좌정보 등 민감정보가 포함된 SMS나 이메일은 입력하지 않도록 안내한다.
- 시연과 테스트에는 합성 또는 개인정보가 제거된 SMS·이메일 샘플만 사용한다.
- 실제 악성 URL에 접속하지 않는다.
- HTML 이메일의 외부 이미지와 추적 픽셀을 로드하지 않는다.
- 사용자가 입력한 SMS, 업로드 파일명과 이메일 내용을 로그에 남기지 않는다.
- 공식 출처 링크는 URL 검증을 통과한 경우에만 활성화한다.

## 18. 테스트 계획

### 단위 테스트

- 정상 SMS 직접 입력과 `input_type="sms"` 분류
- 공백 SMS와 10,000자 초과 SMS 거부
- SMS URL 후보 추출, `[URL]` 치환과 출처 메타데이터 보존
- 입력 유형 전환 시 기존 입력과 분석 결과 초기화
- 문자·이메일 모델에 `text`, `input_type`, `subject`만 전달되는지 확인
- URL 모델에 URL 문자열 하나씩 전달되는지 확인
- `classify_message`·`analyze_urls` Function Calling 도구 스키마 검증
- 도구 인자와 원본 `AnalysisRequest` 불일치 차단
- 여러 Function Calling 결과의 `function_call_output` 반환
- UI와 pipeline에서 TF-IDF 및 URL 모델 특징을 생성하지 않는지 확인
- 정상 `.eml`과 멀티파트 이메일 파싱
- `.EML` 대문자 확장자 허용
- `.eml`이 아닌 확장자 거부
- `invoice.pdf.eml` 등 의심스러운 이중 확장자 거부
- 25MB 이하 파일 허용 및 25MB 초과 파일 거부
- 빈 `.eml` 파일 거부
- PDF·ZIP·PNG·JPEG·GIF·Java class·실행 파일을 `.eml`로 변경한 입력 거부
- 일반 텍스트를 `.eml`로 변경했지만 이메일 헤더가 없는 입력 거부
- 이메일 헤더는 있지만 제목과 본문이 모두 없는 입력 거부
- 파싱 결함을 `parse_warnings`로 반환
- HTML 전용 이메일의 텍스트 추출 및 외부 리소스 미로딩
- 본문이 없는 이메일
- 입력 유형의 `email` 분류
- 일반 텍스트 정규식 및 HTML `href`·외부 이미지 `src` URL 추출, `[URL]` 치환과 본문·URL 분리
- 동일 파일명·다른 내용의 해시 구분
- URL 없음·중복·20개 초과·잘못된 형식·`cid:`·`data:` 처리
- URL 후보 선택·중복 제거·20개 제한이 `url_analyzer.py`에서 한 번만 실행되는지 확인
- URL별 부분 실패
- 요청·응답 `schema_version` 검증
- 점수 범위와 enum 검증

### UI 테스트

- SMS·이메일 입력 유형 선택과 상호 배타적 표시
- SMS 미입력 및 이메일 파일 미선택 상태에서 분석 차단
- SMS 붙여넣기 후 일반 텍스트 미리보기
- 이메일 업로드 후 안전한 미리보기
- 분석 중 중복 요청 차단
- 실제 단계 추정 없이 통합 로딩 표시
- 성공 및 부분 성공 결과 표시
- 의심 URL 비활성화
- 검증된 공식 출처 링크 활성화
- 전체 오류에서 내부 원문 미노출
- 초기화 시 파일 업로더와 세션 상태 제거
- 모바일 한 열 레이아웃

### 대표 E2E 시나리오

1. 정상 SMS
2. 스미싱 SMS
3. 정상 채용 이메일
4. 가짜 채용 이메일
5. URL 없는 SMS·이메일
6. 중복 URL과 여러 URL이 포함된 SMS·이메일
7. 모델 파일 없음
8. OpenAI API 실패
9. Web Search 또는 File Search 결과 없음

## 19. 구현 완료 기준

- 제시된 프로젝트 구조에서 각 모듈 책임이 분리된다.
- SMS 직접 입력과 `.eml` 업로드를 상호 배타적으로 제공한다.
- 유효한 SMS를 `sms`, 유효한 `.eml`을 `email` 유형으로 분류한다.
- SMS 공백·길이 검증과 `.eml` 확장자·크기·내용·이메일 구조 검증을 수행한다.
- SMS 정규화 또는 이메일 파싱 후 URL 추출과 공통 요청 데이터 생성이 자동으로 수행된다.
- 입력 유형과 SMS 텍스트 또는 파일 바이트의 해시로 새로운 입력을 감지한다.
- 일반 텍스트 정규식과 HTML `href`·외부 이미지 `src`에서 URL을 추출한다.
- 공통 요청에는 입력 유형, 선택적 제목, `[URL]`로 치환한 본문과 출처 메타데이터가 포함된 URL 후보를 포함한다.
- URL은 클릭 대상 링크를 우선하여 최초 등장 순서로 중복 제거하고 최대 20개까지 분석한다.
- 초과한 URL 개수가 UI에 표시된다.
- OpenAI Function Calling으로 로컬 모델을 호출하고 결과를 `function_call_output`으로 반환한다.
- TF-IDF와 URL 특징 추출은 각 모델 함수 내부에서 학습 때와 동일하게 수행한다.
- Mock 응답으로 SMS와 이메일 결과 화면을 모두 시연할 수 있다.
- 점수 의미와 배열 내부 스키마가 일관되게 적용된다.
- 의심 URL과 공식 출처 링크가 구분된다.
- 일부 기능 실패 시 나머지 결과가 유지된다.
- API 키, 내부 오류 및 클릭 가능한 의심 URL이 노출되지 않고 데이터 처리 안내가 표시된다.

## 20. 남은 협의 사항

### 확정된 입력 범위

- MVP는 SMS 문자 메시지 직접 입력과 `.eml` 이메일 파일 업로드를 지원한다.
- 두 입력은 동시에 사용하지 않으며 `input_type`은 각각 `sms`, `email`이다.

### 협의 필요 항목

- API 타임아웃과 재시도 횟수
- 공식 출처 허용 도메인 목록
- `overall_risk.score` 계산식과 위험 수준 임계값
- 모델 파일 형식과 버전 관리 방식
