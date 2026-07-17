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

`AnalysisRequest`와 primary `AnalysisResponse`는 현재 `src.client_factory.get_analysis_client()`가 만드는
`src.ui.local_analysis_client.LocalAnalysisClient`의 로컬 계약이다. `LocalAnalysisClient`는
`LocalUrlAnalysisClient`를 확장해 `analyze_message`와 로컬 URL 분석을 결합한다. HTTP
`ApiAnalysisClient`는 구현되어 있지 않으며 이 계약의 현재 경로가 아니다.

이 문서는 primary DTO, 후속 DTO, trust gate와 운영 정책의 정본이다.

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

현재 primary `AnalysisResponse`는 hosted evidence 필드를 제거하지 않는다. 호환성 필드 `web_evidence`와 `file_evidence`는 존재하지만 `LocalAnalysisClient`가 항상 빈 배열로 반환한다. 현재 `status`는 `success`와 `error`만 사용하며, `overall_risk`는 로컬 파이프라인이 산출하고 UI는 재계산하지 않는다. 공통계약의 `partial`은 **향후 계약 capability**일 뿐 현재 local adapter의 emit 값이 아니다.

후속 대화는 별도 `FollowupResponse` DTO로만 공개한다. 이 DTO는 host-rendered action plan, 승인된
`web_evidence`/`file_evidence`, 사용 불가 또는 fallback 안내를 담을 수 있지만 primary
`AnalysisResponse`의 분류·점수·임계값·`status`에 영향을 주지 않는다.

## 5. 분석 파이프라인 처리 흐름

공통계약의 1차 분석 흐름은 고정된 로컬 문자·이메일·URL 모델만 사용한다. OpenAI는 1차
분류·라벨·점수·임계값·`AnalysisResponse`를 생성하거나 변경하지 않는, 분석 완료 뒤의 선택적
후속 대화 경계다.

```text
Streamlit UI
→ AnalysisClient.analyze(AnalysisRequest)
→ `get_analysis_client()` → `LocalAnalysisClient` → 후보 선택·중복 제거·상한 적용 → 상속 URL adapter → `url_analyzer.analyze_url`
→ 로컬 overall_risk·AnalysisResponse 반환
→ [사용자 후속 질문 + capability 준비 시]
→ Responses 1: build_security_action_plan 강제 Function Calling
→ 호스트의 결정론적 action plan
→ Responses 2: 공식-domain Web Search / attested File Search 보조 근거
→ 검증된 보조 설명만 후속 대화에 반환
```

후속 흐름은 하나의 보안 비서 페르소나와 모델 설정이 수행하는 **제한된 두 호출**이다. Agents SDK,
handoff, Assistant 리소스, 복수 assistant·페르소나, Agent Orchestrator는 사용하지 않으며 계획
범위에도 없다.

첫 호출은 strict `build_security_action_plan`만 노출하고 강제한다. `parallel_tool_calls=False`,
`store=False`와 낮은 reasoning을 사용하며, 허용된 암호화 reasoning 항목과 정확히 한 completed
function call만 수락한다. dispatcher는 검증된 불변 `{request_id,risk_level}`만 받아 I/O 없이 한 번
실행하고 `classification_unchanged:true`인 정준 action plan을 호스트에서 렌더링한다.

두 번째 호출은 첫 호출에서 수락한 원래 입력, 암호화 reasoning/function 항목을 순서와 바이트 그대로
재생하고 일치하는 `function_call_output`을 추가한 뒤에만 수행한다. `previous_response_id`는 사용하지
않고, 두 호출 모두 `store=False`다. 이 호출에는 OpenAI 호스팅 공식 HTTPS 도메인 Web Search와
attestation·manifest·inventory·readiness·provenance가 모두 유효한 경우의 File Search만 제공한다.
모든 claim과 citation은 엄격한 URL/파일/도구결과 결속 검증을 통과해야 하며, 하나라도 실패하면 생성된
보조 claim·citation 전체를 폐기하고 action-plan fallback만 반환한다.

provider trust는 opt-in, 키, 모델, SDK와 provider contract integrity anchor 검증이 모두 성공한 경우에만
성립한다. 하나라도 실패하면 OpenAI 또는 Vector client를 만들거나 Responses 호출을 전혀 만들지 않는다.
provider trust가 성립한 뒤에만 File gate를 별도로 평가한다. manifest·inventory·readiness·provenance 및
`OPENAI_VECTOR_STORE_ID`와 verified inventory store ID의 exact match 중 하나라도 실패하면 File Search만
생략하며 Web-only fallback은 허용한다. 로컬 1차 분석은 언제나 계속 제공한다.

## 6. 후속 근거 승인 경계

후속 공개 결과에는 provider response ID, file ID, vector store ID 또는 encrypted reasoning을 포함하지
않는다. 호스트가 만드는 무작위 `response_scope`와 zero-based evidence ordinal로만 근거를 표현한다.
Web 근거는 canonicalized 공식 HTTPS URL이 하나의 claim 및 완료된 단일 Web Search call source/action과
정확히 결속될 때만 승인한다. File 근거는 fresh attested inventory, 정규화한 대소문자 구분 파일명,
완료된 단일 File call의 정확한 result와 annotation이 모두 일치할 때만 승인한다.

중복·고아·surplus·unknown·mismatch annotation/result, 형상 오류 또는 claim 범위 밖 인용은 전역
fail-closed 조건이다. 이때 모델이 만든 보조 주장과 인용은 전부 버리고, host-rendered action plan과
안전한 degradation/fallback 상태만 반환한다. 의심 URL은 검색 근거와 섞지 않으며 검색 근거가 없어도
안전을 의미하지 않는다.

## 7. 상태(status)·오류 코드 기준

### 7.1 현재 local adapter status 판정 기준

| status | 조건 |
|---|---|
| `success` | 메시지 분석 또는 선택된 URL 분석 중 하나 이상이 성공 |
| `error` | 메시지와 선택된 모든 URL 분석이 실패 |

일부 URL 실패는 성공한 메시지·URL 결과와 함께 `url_analysis_summary.failed_count`, URL별 결과 및 `errors`에 남는다. 현재 `LocalAnalysisClient`는 `partial`을 emit하지 않는다. `partial` 규칙은 향후 공통계약 capability로만 보존한다.

### 7.2 향후 공통계약 오류 코드 capability

| code | component | 의미 | retryable |
|---|---|---|---|
| `INVALID_INPUT` | request | 요청 필수 값 누락·형식 오류 | false |
| `SCHEMA_VERSION_MISMATCH` | request | 지원하지 않는 `schema_version` | false |
| `MESSAGE_MODEL_FAILED` | message_analysis | `analyze_message()` 실행 실패 | true |
| `URL_MODEL_FAILED` | url_analysis | 특정 URL에 대한 `analyze_url()` 실행 실패 | true |
| `FOLLOWUP_UNAVAILABLE` | followup | capability 또는 provider/File 전제조건 미충족 | false |
| `CITATION_REJECTED` | followup | 보조 근거 결속 검증 실패; action plan만 유지 | false |
| `OPENAI_API_ERROR` | followup | 선택적 후속 Responses 호출 실패 | false |
| `RESPONSE_VALIDATION_FAILED` | api | 조립한 응답이 계약을 만족하지 못함 | false |
| `INTERNAL_ERROR` | api | 그 외 처리되지 않은 서버 내부 오류 | false |

위 표의 필드 형식은 **향후 공통계약 capability**다. 현재 `LocalAnalysisClient`의 URL 오류 항목은 `code`, `message`, `url`을 기록하고, 메시지 오류 항목은 `component`, `code`, `message`, `retryable`을 기록한다. 어느 경우에도 `message`는 UI에 그대로 노출해도 되는 사용자용 문구여야 하며, 원문·API 키·내부 파일 경로·스택트레이스를 포함하지 않는다.

## 8. 모델 함수 계약

`analyze_message`, `analyze_url`은 각 모델팀이 구현한다. 현재 API 파이프라인은 `get_analysis_client()`가 만든 `LocalAnalysisClient`에서 `analyze_message`를 호출하고, 상속 URL adapter가 `url_analyzer.analyze_url`을 호출한다. 정식 계약은 `SafeMate_모델_UI_연동_요구사항.md`에서 정의한다.

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

- `LocalAnalysisClient`는 `analyze_message(payload["body"], payload["input_type"], payload["subject"])`를 호출한다.
- `LocalAnalysisClient`는 `src.ui.url_candidates`로 URL 후보를 재검증·중복 제거·우선순위화한 뒤 최대 20개의 `candidate["url"]`을 선택한다.
- `LocalAnalysisClient`는 선택된 URL을 `LocalUrlAnalysisClient`를 통해 `analyze_url()`에 하나씩 전달하고, URL 후보의 위치·출처·표시 주소 메타데이터와 HTML 정적 검사 신호를 모델 결과에 병합한다. `url_analyzer.py`는 URL 추론만 수행한다.
- URL 모델이 반환한 `url`이 입력 문자열과 다르면 계약 오류로 처리한다.
- `top_features`·`features`는 설명값이 없더라도 빈 배열이어야 한다.
- 모델별 `error`는 성공 시 `null`, 실패 시 안전한 오류 객체여야 한다.
- 모델 반환값은 `json.dumps(result, allow_nan=False)`로 직렬화할 수 있어야 한다.

## 9. 파일 배치와 환경변수

### 9.1 파일 배치

공통계약 3절의 `AnalysisClient` 구현 구조에 맞춰 배치한다.

| 대상 | 위치할 파일 |
|---|---|
| `get_analysis_client()` 및 `AnalysisClient` 경계 | `src/client_factory.py`, `src/contracts.py` |
| 현재 primary DTO 조립 | `src/ui/local_analysis_client.py` |
| 로컬 URL adapter·후보 우선순위화 | `src/ui/local_url_client.py`, `src/ui/url_candidates.py` |
| `analyze_message` 로컬 모델 실행 | `src/analyzers/text_analyzer.py` |
| `analyze_url` 로컬 모델 실행 | `src/analyzers/url_analyzer.py` |
| Responses 기반 후속 DTO, action plan·근거 승인 | `src/services/openai_client.py` |
| 최대 URL 개수, 위험 임계값, 타임아웃 설정 | `src/config.py` |

### 9.2 환경변수 이름

| 환경변수 이름 | 용도 |
|---|---|
| `SAFEMATE_OPENAI_FOLLOWUP_ENABLED` | 기본 false의 후속 capability opt-in |
| `OPENAI_API_KEY` | 활성화된 후속 Responses 호출용 API 키 |
| `OPENAI_MODEL` | 단일 보안 비서 페르소나의 모델 식별자 |
| `OPENAI_VECTOR_STORE_ID` | File Search 호출 전 verified inventory의 store ID와 exact-match해야 하는 값 |
| `OPENAI_VECTOR_INVENTORY_ATTESTATION_PATH` | private ID를 포함하는 불변 Vector inventory artifact 경로 |
| `OPENAI_VECTOR_INVENTORY_ATTESTATION_SHA256` | Vector inventory artifact의 보호된 정준 SHA-256 |
| `OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH` | 운영자가 발행한 활성 provider attestation 경로 |
| `OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256` | 활성 provider attestation의 보호된 정준 SHA-256 |
| `OPENAI_SDK_VERSION` | provider contract와 일치해야 하는 OpenAI SDK 버전 |

### 9.3 운영 요구사항

- **결정됨:** 후속 기능은 기본 비활성화다. opt-in, 키, 모델, SDK 및 provider contract integrity anchor가 모두 검증될 때만 provider client를 지연 생성한다. provider trust 실패 시 Responses 호출을 전혀 만들지 않는다.
- **결정됨:** provider trust 뒤 manifest·inventory·readiness·provenance 또는 `OPENAI_VECTOR_STORE_ID`의 verified inventory store-ID exact match가 실패하면 File Search만 fail-closed하고 Web-only fallback은 허용한다.
- **결정됨:** 현재 primary DTO는 local-only이며 `web_evidence`와 `file_evidence` 호환성 슬롯을 빈 배열로 유지한다. 현재 primary `status`는 `success|error`뿐이다. `partial`은 향후 공통계약 capability다. hosted action plan·citation은 별도 `FollowupResponse` DTO에만 있으며 primary score·label·threshold·status를 변경하지 않는다.
- **결정됨:** 최대 분석 URL은 `MAX_URLS_TO_ANALYZE=20`이고 위험 수준은 score `<0.4`=`low`, `0.4 이상 0.7 미만`=`medium`, `0.7 이상`=`high`다.
- 후속 경로는 `store=False`, `max_retries=0`, 호출당 최대 20초, readiness 확인당 최대 5초, 사용자 턴 최대 45초, 최대 두 호출·한 dispatcher·최대 다섯 hosted tool 호출의 경계를 사용한다.
- configured digest는 deployment-controlled integrity anchor이며, 손상된 런타임에 대한 암호학적 증명이 아니다. 운영자는 artifact와 configured digest의 custody·rotation·rollout을 책임진다.
- live provider 검증은 `--run-openai-integration`, `RUN_OPENAI_INTEGRATION=1`, `OPENAI_INTEGRATION_COST_ACK=YES`가 모두 필요한 비용 게이트의 운영자 절차에서만 수행하며 CI에는 `OPENAI_INTEGRATION_TRUSTED_RUNNER=1`도 필요하다.


## 10. 향후 HTTP API 전환 규칙

공통계약 12절을 그대로 따른다. 로컬 `AnalysisClient` 계약을 HTTP 전송 형식으로 그대로 감싼다.

```http
POST /analysis
Content-Type: application/json
```

요청 본문은 `AnalysisRequest`, 성공 응답 본문은 `AnalysisResponse`를 사용한다.

| HTTP 상태 | 사용 조건 |
|---|---|
| `200` | 현재 local adapter의 분석 응답(`status`가 `success` 또는 `error`) |
| `400` | 요청 스키마·입력 검증 실패 |
| `413` | 업로드 크기 제한 초과 |
| `500` | 복구할 수 없는 내부 오류 |

향후 HTTP 전환에서 `partial`을 도입할 경우에만, URL 하나의 실패를 HTTP 500이 아닌 응답 본문의 부분 실패로 표현한다. 현재 local adapter는 URL 개별 실패를 `errors`와 URL별 결과에 기록하면서 `status`는 `success` 또는 `error`로 유지한다.

## 11. 운영 후속 과제

- `ApiAnalysisClient`(HTTP 래퍼) 구현
- API 기술명세서 9.3절의 결정된 운영 정책에 따라 운영자 manifest 승인, artifact custody·rotation 및 비용-gated live 검증 절차 유지

Agent Orchestrator 또는 다중 assistant 전환은 범위에 포함하지 않는다.
## 12. 남은 협의 사항

- 8절 모델 함수 계약과 실제 모델 구현이 `SafeMate_모델_UI_연동_요구사항.md` 기준으로
  일치하는지 최종 확인
