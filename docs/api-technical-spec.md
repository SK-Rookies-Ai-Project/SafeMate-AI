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

> 이메일 분류 모델(`analyze_message`)과 URL 분석 모델(`analyze_url`)이 반환할 상세 값은
> `SafeMate_모델_UI_연동_요구사항.md`가 별도로 정의한다. 이 문서 8절은 그 문서가 아직 공유되기
> 전까지 API 팀이 잡아둔 초안이며, 모델팀 확인 후 8절을 해당 문서 기준으로 갱신한다.

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
→ AnalysisClient.analyze(AnalysisRequest)
→ 메시지 분류 모델 호출
→ URL 분석 모델 반복 호출
→ Web Search / File Search 근거 취합
→ AnalysisResponse 반환
```

로컬 모델 호출은 OpenAI에 판단을 맡기지 않는다. 즉 "이메일이 피싱인지"는 파이프라인 코드가
`analyze_message()`, `analyze_url()`을 **직접, 순서대로** 호출해서 얻는다. OpenAI(Responses API)는
아래 두 가지에만 쓰인다.

1. 내장 `web_search`·`file_search` 도구로 관련 공식 자료·최신 사례를 찾는다.
2. 로컬 모델 결과와 검색 근거를 근거로 사람이 읽을 `summary`, `risk_reasons`, `recommended_actions`
   문장을 생성한다.

```text
1) AnalysisRequest 검증 통과 (3절)
        ↓
2) analyze_message(body) 직접 호출 → message_analysis 채움
        ↓
3) url_candidates 재검증·중복 제거 → 각 URL마다 analyze_url(candidate) 직접 호출
   → url_analysis, url_analysis_summary 채움
        ↓
4) Responses API 호출 (web_search, file_search 도구 사용)
   client.responses.create(
       model=...,
       tools=[{"type": "web_search"}, {"type": "file_search", "vector_store_ids": [...]}],
       input=[... message_analysis·url_analysis 요약, 원본 이메일 맥락 ...],
   )
        ↓
5) 응답에서 검색 결과를 추출해 web_evidence·file_evidence로 정규화 (6절)
        ↓
6) 같은 응답(또는 후속 호출)에서 summary·risk_reasons·recommended_actions 텍스트를 받는다
        ↓
7) overall_risk 산출
- 메시지 모델의 phishing_probability와 URL 모델의 risk_score를 분석 통합 파이프라인에서 처리한다.
- GPT나 UI는 score를 계산하지 않는다.
- 초기 버전(MVP)은 유효한 점수 중 최댓값(max)을 overall_risk.score로 사용한다.
- Web Search·File Search 결과는 점수 계산이 아니라 위험 근거(evidence) 생성에만 활용한다.
        ↓
8) 상태(status) 판정 후 AnalysisResponse 조립·반환 (7절)
```
### Search 호출 정책

- Responses API는 필요 시 Web Search와 File Search를 호출한다.
- File Search는 호출당 최대 5개의 관련 결과를 반환한다.
- Web Search는 결과 개수 제한을 두지 않는다.
- Search 호출 여부는 GPT가 판단한다.
- 응답당 Tool(Function Calling)은 최대 6회까지 호출한다.

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

## 8. 모델 함수 계약 (모델팀 확인 필요)

`analyze_message`, `analyze_url`은 각 모델팀이 구현하고 API 파이프라인이 직접 호출하는 함수이다
(공통계약 13절 "책임 분리"). 정식 계약은 `SafeMate_모델_UI_연동_요구사항.md`에서 정의하며, 아래는
그 문서가 공유되기 전까지 API 팀이 공통계약 6·8절의 `message_analysis`·`url_analysis` 필드를
역산해 잡아둔 초안이다.

```python
def analyze_message(body: str) -> dict:
    """
    return {
        "label": "normal" | "phishing" | "unknown",
        "phishing_probability": float | None,   # 0.0 ~ 1.0
        "signals": list[str],
        "top_features": list[{"name": str, "value": float, "contribution": float}],
        "model_version": str,
    }
    """

def analyze_url(candidate: dict) -> dict:
    """
    candidate: AnalysisRequest.url_candidates의 항목 하나
    return {
        "label": "benign" | "suspicious" | "malicious" | "unknown",
        "risk_score": float | None,   # 0.0 ~ 1.0
        "signals": list[str],
        "features": list[{"name": str, "raw_value": float, "normalized_value": float, "contribution": float}],
        "model_version": str,
    }
    """
```

### 모델팀에 확인할 항목

- `SafeMate_모델_UI_연동_요구사항.md` 공유 후, 위 초안과 실제 반환 필드·자료형이 일치하는지 확인
- `label` enum 값이 공통계약과 정확히 일치하는지(`message_analysis`: `normal`/`phishing`/`unknown`,
  `url_analysis`: `benign`/`suspicious`/`malicious`/`unknown`)
- `top_features`·`features`가 항상 배열로 오는지(설명값이 없을 때 `null`이 아니라 빈 배열인지,
  공통계약 6·8절 기준)
- 모델 실패 시 예외를 던지는지, `error` 필드로 실패를 알리는지
- `model_version` 표기 규칙과 버전 변경 시 API에 알리는 절차

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
| `OPENAI_VECTOR_STORE_ID` | File Search가 검색할 Vector Store ID |


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

- 8절 모델 함수 계약을 `SafeMate_모델_UI_연동_요구사항.md` 기준으로 최종 확정