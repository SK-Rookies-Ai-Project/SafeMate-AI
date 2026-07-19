---
title: SafeMate AI API 기술명세서
created: 2026-07-14
updated: 2026-07-15
version: v0.2
status: draft
owner: 손미덕
team: 자비스
project: SafeMate AI
---

# SafeMate AI API 기술명세서

## 1. 문서 목적

`SafeMate_분석_통합_UI_공통계약.md`에서 고정한 `AnalysisRequest`·`AnalysisResponse` 계약을 API(분석
파이프라인)가 어떻게 채우는지 정의한다. 이 문서는 계약을 새로 정의하지 않으며, 계약 자체가
바뀌면 `SafeMate_분석_통합_UI_공통계약.md`를 먼저 수정한 뒤 이 문서를 따라 수정한다.

> 이메일 분류 모델(`analyze_message`)과 URL 분석 모델(`analyze_url`)의 입력·반환 계약은
> `SafeMate_모델_UI_연동_요구사항.md`를 따른다.

## 2. 공통 계약 원칙

`AnalysisRequest`와 `AnalysisResponse`는 로컬 파이프라인(`LocalAnalysisClient`)과 향후 HTTP
API(`ApiAnalysisClient`)가 공유하는 단일 계약이다(공통계약 3절). API 문서가 정의하는 범위는
입출력 형식이 아니라 그 형식을 채우기 위한 내부 처리 방법이다. 즉 파이프라인 호출 순서, 검색
결과 정규화, 상태·오류 판정 기준이 이 문서의 실제 내용이다.

계약을 변경해야 할 일이 생기면 `SafeMate_분석_통합_UI_공통계약.md`와 이 문서를 함께 수정하고,
`schema_version`을 함께 올린다.

## 3. 요청 스키마: AnalysisRequest

공통계약 4절과 동일한 스키마이다.

```json
{
  "schema_version": "1.0",
  "request_id": "analysis-a1b2c3d4",
  "input_type": "email",
  "subject": "계정 확인 안내",
  "body": "계정 확인을 위해 [URL]에 접속하세요.",
  "url_candidates": [
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
  ]
}
```

### API 재검증 항목

- 지원하는 `schema_version`인지 확인
- `input_type`이 `sms` 또는 `email`인지 확인, `sms`이면 `subject`가 `null`인지 확인
- `body`에 URL 원문이 남아 있지 않고 `[URL]`로 치환되었는지 확인(요청 불변 조건 1)
- `url_candidates`의 각 항목이 `url`, `source_type`, `input_index`를 갖추었는지 확인
- `source_type`이 `text`, `href`, `image_src` 중 하나인지 확인
- 요청 본문 전체 크기가 허용 범위 이내인지 확인

공통계약 4.3절 요청 불변 조건(모델·LLM이 요청에 없던 URL을 추가할 수 없음, 요청 원문·API 키를
로그에 남기지 않음)은 API 파이프라인 전 구간에서 유지한다.

## 4. 응답 스키마: AnalysisResponse

공통계약 5절과 동일한 스키마이다. API는 이 형태를 그대로 만들어 반환하며, 필드를 임의로 줄이거나
이름을 바꾸지 않는다.

```json
{
  "schema_version": "1.0",
  "request_id": "analysis-a1b2c3d4",
  "input_type": "email",
  "status": "success",
  "overall_risk": { "level": "high", "score": 0.84 },
  "summary": "...",
  "risk_reasons": ["..."],
  "recommended_actions": ["..."],
  "message_analysis": {
    "status": "success",
    "label": "phishing",
    "phishing_probability": 0.84,
    "signals": ["..."],
    "top_features": [{ "name": "비밀번호", "value": 1.0, "contribution": 0.31 }],
    "model_version": "message-v1",
    "error": null
  },
  "url_analysis_summary": {
    "candidate_count": 3,
    "analyzed_count": 2,
    "omitted_url_count": 1,
    "failed_count": 0
  },
  "url_analysis": [
    {
      "url": "https://evil.example/login",
      "input_indexes": [0, 2],
      "occurrence_count": 2,
      "source_types": ["text", "href"],
      "status": "success",
      "label": "suspicious",
      "risk_score": 0.78,
      "signals": ["..."],
      "features": [{ "name": "URL 길이", "raw_value": 83, "normalized_value": 0.72, "contribution": 0.18 }],
      "displayed_url": "https://official.example/login",
      "displayed_domain": "official.example",
      "destination_domain": "evil.example",
      "display_href_mismatch": true,
      "model_version": "url-v1",
      "error": null
    }
  ],
  "web_evidence": [],
  "file_evidence": [],
  "limitations": [],
  "errors": []
}
```

필드 의미와 값 범위(`status` enum, `overall_risk.level` enum, 점수 범위 0.0~1.0 등)는 공통계약
5~10절을 그대로 따른다. `status`는 `success`, `partial`, `error` 세 값만 사용한다.(공통계약 5.1절),`overall_risk`는 API(분석
파이프라인)가 산출하며, UI는 이 값을 재계산하지 않는다(공통계약 5.2절).

## 5. 분석 파이프라인 처리 흐름

공통계약 2절이 정의한 흐름은 다음과 같다.

```text
Streamlit UI
→ Responses API: run_local_security_analysis 강제 Function Calling
→ 호스트: 검증된 AnalysisRequest로 로컬 메시지·URL 모델 실행
→ function_call_output 전달
→ Responses API: Web Search / 선택적 File Search
→ 로컬 AnalysisResponse + 별도 추가 조사 결과 반환
```

로컬 모델 호출 여부는 Function Calling 흐름으로 표현하지만 실제 입력과 실행 권한은 호스트가
보유한다. 모델이 생성하는 함수 인자는 `analysis_scope="full"` 하나뿐이며 본문·제목·URL 후보·요청
ID를 포함하거나 교체할 수 없다. 피싱 분류와 점수는 호스트가 `analyze_message()`와
`analyze_url()`을 호출해 얻은 결과만 사용한다.

1. 내장 `web_search`·`file_search` 도구로 관련 공식 자료·최신 사례를 찾는다.
2. 로컬 모델 결과와 검색 근거를 근거로 사람이 읽을 `summary`, `risk_reasons`, `recommended_actions`
   문장을 생성한다.

```text
1) AnalysisRequest 검증 후 호스트 메모리에 보관 (3절)
        ↓
2) Responses API가 strict run_local_security_analysis 함수 호출 반환
        ↓
3) 호스트가 함수명·call_id·{"analysis_scope":"full"}을 검증
        ↓
4) 보관한 요청으로 analyze_message()와 analyze_url()을 실행해 로컬 AnalysisResponse 생성
        ↓
5) 동일 call_id의 function_call_output으로 로컬 결과 전달
        ↓
6) 후속 Responses 호출에 web_search와 선택적 file_search만 제공
        ↓
7) 로컬 AnalysisResponse와 추가 조사 텍스트·도구·인용을 별도 필드로 UI에 반환
```

메시지 모델의 `phishing_probability`와 URL 모델의 `risk_score`는 로컬 통합 코드가 처리한다.
GPT나 UI는 점수를 계산하거나 로컬 `status`를 변경하지 않는다. Web/File Search 실패 시 이미
완료된 로컬 결과를 그대로 유지하고 추가 조사만 비운다. 첫 Responses 호출 자체가 실패하면 같은
로컬 분석기를 직접 한 번 실행한다.
### Search 호출 정책

- Responses API는 필요 시 Web Search와 File Search를 호출한다.
- File Search는 호출당 최대 5개의 관련 결과를 반환한다.
- Web Search는 결과 개수 제한을 두지 않는다.
- Search 호출 여부는 GPT가 판단한다.
- 응답당 OpenAI 도구 호출은 최대 6회까지 허용한다.

### 처리 시 유의사항

- 2·3단계는 OpenAI 호출 없이 우리 서버(또는 같은 프로세스) 안에서 실행하는 일반 Python 함수
  호출이다. 로컬 모델 실행이 실패해도 OpenAI API와는 무관한 오류이므로 8절 오류 코드로 별도
  기록한다.
- `url_candidates`가 빈 배열이면 3단계를 건너뛰고 `url_analysis`를 빈 배열, `url_analysis_summary`의
  모든 값을 0으로 채운다.
- URL 하나의 분석 실패가 다른 URL 결과나 메시지 분석 결과에 영향을 주지 않는다.
- 4단계 Responses API 호출이 실패하면(OpenAI API 오류 등) 이미 확보한 `message_analysis`,
  `url_analysis` 결과는 유지한 채 `status: "partial"` 또는 `"error"`로 응답한다(7절 판정 기준 참고).
- LLM은 `url_candidates`에 없던 URL을 근거나 요약에 새로 만들어 넣을 수 없다(공통계약 4.3절
  불변 조건 4와 동일한 원칙을 응답 생성 단계에도 적용).

## 6. Web Search·File Search 근거 정규화

OpenAI가 돌려주는 `web_search`·`file_search` 도구 결과는 필드 이름과 구조가 공통계약의
`web_evidence`·`file_evidence`와 다르므로, API가 아래 규칙으로 변환한다.

### 6.1 web_evidence (공통계약 9.1절)

| 필드 | 필수 | 정규화 규칙 |
|---|---|---|
| `title` | 필수 | 검색 결과 페이지 제목 |
| `organization` | 필수 | 도메인·페이지 정보로 유추, 불확실하면 발행 주체를 알 수 있는 범위까지만 채움 |
| `published_at` | 선택 | 검색 결과에 게시일이 있는 경우만 채움 |
| `summary` | 선택 | 검색 결과 스니펫을 그대로 쓰지 않고 100자 이내로 요약 |
| `url` | 필수 | `http`/`https` 스킴과 허용 도메인 검증을 통과한 경우만 채움, 실패 시 해당 항목 자체를 제외 |

### 6.2 file_evidence (공통계약 9.2절)

| 필드 | 필수 | 정규화 규칙 |
|---|---|---|
| `title` | 필수 | Vector Store 문서 제목(메타데이터), 없으면 파일명 사용 |
| `organization` | 필수 | 문서 메타데이터의 발행 기관 |
| `filename` | 필수 | 업로드 시 등록한 원본 파일명 |
| `page` | 선택 | File Search가 반환하는 인용 위치(페이지/섹션) |
| `excerpt` | 선택 | 인용문을 그대로 옮기지 않고 100자 이내로 요약 |
| `external_url` | 선택 | 문서 내 검증된 외부 링크가 없으면 `null` |

### 공통 규칙

- File Search는 관련도 순으로 최대 5개의 결과를 반환한다.
- Web Search는 결과 개수 제한을 두지 않는다.
- 같은 문서·같은 URL이 중복 검색되면 하나로 합친다.
- 의심 URL(`url_analysis`)과 검색 근거 URL(`web_evidence`)을 같은 배열에 섞지 않는다(공통계약 9.2절). 의심 URL은 클릭 가능한 링크로 표시하지 않는다.

## 7. 상태(status)·오류 코드 기준

### 7.1 status 판정 기준 (공통계약 11절)

| status | 조건 |
|---|---|
| `success` | 필수 메시지 분석과 모든 필수 URL 분석이 성공 |
| `partial` | 메시지 분석은 성공했지만, 일부 URL 또는 검색 기능이 실패 |
| `error` | 필수 메시지 분석이 실패했거나 전체 분석이 불가능한 경우 |

부분 실패 시 성공한 메시지·URL 분석 결과는 그대로 유지한다.

### 7.2 오류 코드

| code | component | 의미 | retryable |
|---|---|---|---|
| `INVALID_INPUT` | request | 요청 필수 값 누락·형식 오류 | false |
| `SCHEMA_VERSION_MISMATCH` | request | 지원하지 않는 `schema_version` | false |
| `MESSAGE_MODEL_FAILED` | message_analysis | `analyze_message()` 실행 실패 | true |
| `URL_MODEL_FAILED` | url_analysis | 특정 URL에 대한 `analyze_url()` 실행 실패 | true |
| `FILE_SEARCH_FAILED` | file_evidence | Vector Store 검색 실패 또는 타임아웃 | true |
| `SEARCH_TIMEOUT` | web_evidence | Web Search 응답 지연·타임아웃 | true |
| `OPENAI_API_ERROR` | openai | Responses API 호출 자체가 실패(인증·요금·서버 오류) | true |
| `RESPONSE_VALIDATION_FAILED` | api | 조립한 응답이 계약을 만족하지 못함 | false |
| `INTERNAL_ERROR` | api | 그 외 처리되지 않은 서버 내부 오류 | false |

`errors` 배열의 각 항목은 공통계약 10절 형식 `{ "component", "code", "message", "retryable",
"item_index" }`을 따른다. `item_index`는 `url_analysis`처럼 배열 항목 중 하나가 실패했을 때만
채우고, 그 외에는 생략한다. `message`는 UI에 그대로 노출해도 되는 사용자용 문구여야 하며, 원문·API
키·내부 파일 경로·스택트레이스를 포함하지 않는다(공통계약 10절).

## 8. 모델 함수 계약

`analyze_message`, `analyze_url`은 각 모델팀이 구현하고 API 파이프라인이 직접 호출하는 함수이다. 정식 계약은 `SafeMate_모델_UI_연동_요구사항.md`에서 정의한다.

```python
from typing import Literal


def analyze_message(
    text: str,
    input_type: Literal["sms", "email"],
    subject: str | None = None,
) -> dict:
    """Return the message-model result defined by the model–UI contract."""
    ...


def analyze_url(url: str) -> dict:
    """Return the URL-model result defined by the model–UI contract."""
    ...
```

호출과 통합 규칙:

- API는 `analyze_message(payload["body"], payload["input_type"], payload["subject"])`를 호출한다.
- API는 URL 후보를 재검증·중복 제거·우선순위화한 뒤 최대 20개의 `candidate["url"]`을 `analyze_url()`에 하나씩 전달한다.
- URL 후보의 위치·출처·표시 주소 메타데이터와 HTML 정적 검사 신호는 API가 모델 결과에 병합한다.
- URL 모델이 반환한 `url`이 입력 문자열과 다르면 계약 오류로 처리한다.
- `top_features`·`features`는 설명값이 없더라도 빈 배열이어야 한다.
- 모델별 `error`는 성공 시 `null`, 실패 시 안전한 오류 객체여야 한다.
- 모델 반환값은 `json.dumps(result, allow_nan=False)`로 직렬화할 수 있어야 한다.

## 9. 파일 배치와 환경변수

### 9.1 파일 배치

공통계약 3절의 `AnalysisClient` 구현 구조에 맞춰 배치한다.

| 대상 | 위치할 파일 |
|---|---|
| `LocalAnalysisClient.analyze()`, 파이프라인 순서 (5절) | `src/pipeline.py` |
| `analyze_message` 로컬 모델 실행 | `src/analyzers/text_analyzer.py` |
| `analyze_url` 로컬 모델 실행 | `src/analyzers/url_analyzer.py` |
| Responses API 호출(web_search·file_search), 근거 정규화, 요약 생성 (5·6절) | `src/services/openai_client.py` |
| `AnalysisRequest` 재검증, 상태 판정, 응답 조립 (3·4·7절) | `src/pipeline.py` |
| 향후 `ApiAnalysisClient`(HTTP 래퍼, 10절) | `src/services/api_client.py` (신규) |
| 최대 URL 개수, 타임아웃 등 설정값 | `src/config.py` |

### 9.2 환경변수 이름

| 환경변수 이름 (가칭) | 용도 |
|---|---|
| `OPENAI_API_KEY` | Responses API, File Search, Web Search 호출용 OpenAI API 키 |
| `OPENAI_MODEL` | 후속 보안 채팅에 사용할 OpenAI 모델 식별자 |
| `OPENAI_VECTOR_STORE_ID` | File Search가 검색할 Vector Store ID |

### 9.3 확정된 운영 정책

- OpenAI Responses API 호출은 시도당 60초 타임아웃과 최대 2회 재시도(최초 호출 포함 총 3회)를
  적용한다. SDK가 재시도 가능하다고 판정하는 연결 오류, 타임아웃, rate limit, 서버 오류에만
  지수 백오프를 적용하며 인증 및 잘못된 요청 오류는 재시도하지 않는다.
- `overall_risk.score`는 유효한 `message_analysis.phishing_probability`와 모든
  `url_analysis[].risk_score`의 최댓값으로 산출한다. 숫자가 아니거나, 유한하지 않거나,
  `0.0~1.0` 범위를 벗어난 값은 제외한다. 유효한 점수가 없으면 `score: null`, `level: unknown`이다.
- 위험 단계는 `[0.0, 0.4)`를 `low`, `[0.4, 0.7)`를 `medium`, `[0.7, 1.0]`을 `high`로 판정한다.
- Web Search와 UI 링크 검증은 `src/services/web_search.py`의 동일한 고정 allowlist를 사용한다.
  허용 대상은 11개 국내 공공기관 도메인의 HTTPS 기본 포트 및 정상 하위 도메인뿐이며,
  환경변수로 목록을 확장하지 않는다.
  허용 도메인은 `kisa.or.kr`, `boho.or.kr`, `krcert.or.kr`, `police.go.kr`, `fss.or.kr`,
  `privacy.go.kr`, `pipc.go.kr`, `ncsc.go.kr`, `msit.go.kr`, `gov.kr`, `korea.kr`이다.


## 10. 향후 HTTP API 전환 규칙

공통계약 12절을 그대로 따른다. 로컬 `AnalysisClient` 계약을 HTTP 전송 형식으로 그대로 감싼다.

```http
POST /analysis
Content-Type: application/json
```

요청 본문은 `AnalysisRequest`, 성공 응답 본문은 `AnalysisResponse`를 사용한다.

| HTTP 상태 | 사용 조건 |
|---|---|
| `200` | 분석 성공 또는 부분 성공(`status`가 `success` 또는 `partial`) |
| `400` | 요청 스키마·입력 검증 실패 |
| `413` | 업로드 크기 제한 초과 |
| `500` | 복구할 수 없는 내부 오류 |

로컬 모델의 개별 실패는 가능한 경우 HTTP 500으로 변환하지 않고 `AnalysisResponse.status="partial"`과
`errors`에 기록한다. 즉 "URL 하나 분석 실패"는 HTTP 계층의 오류가 아니라 응답 본문 안의 부분
실패로 표현한다.

## 11. 향후 개발

- Web Search·File Search 실제 연동 및 근거 정규화 구현
- `ApiAnalysisClient`(HTTP 래퍼) 구현
- `overall_risk.score` 산출 로직 고도화
(초기 버전은 메시지 모델의 phishing_probability와 URL 모델의 risk_score 중 유효한 최댓값(max)을 사용하며, 향후 고도화 시 추가 점수 산출 정책을 검토한다.)
- Agent Orchestrator(여러 분석 단계를 조율하는 멀티에이전트 구조)

## 12. 남은 협의 사항

- 8절 모델 함수 계약과 실제 모델 구현이 `SafeMate_모델_UI_연동_요구사항.md` 기준으로
  일치하는지 최종 확인
