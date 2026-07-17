---
title: SafeMate AI API 기능명세서
created: 2026-07-14
updated: 2026-07-15
version: v0.2
status: draft
owner: 손미덕
team: 자비스
project: SafeMate AI
---

# SafeMate AI API 기능명세서

## 1. 문서 목적

`SafeMate_분석_통합_UI_공통계약.md`가 고정한 `AnalysisRequest`·`AnalysisResponse`를 채우기 위해
API(분석 파이프라인)가 수행해야 할 기능과 완료 조건을 정의한다.

> 이 문서는 입출력 형식을 독자적으로 정의하지 않는다. 요청·응답 형식은
> `SafeMate_분석_통합_UI_공통계약.md`(이하 공통계약) 4~10절, API 기술명세서 3~4절에 정의된 계약을
> 그대로 따른다.

## 2. 담당 범위

이 문서는 현재 로컬 분석 경로와 별도 후속 대화의 기능 요구사항을 다룬다. 현재 책임 경계는
`get_analysis_client()` → `LocalAnalysisClient`이며, 화면의 관찰 가능한 동작은 UI 명세서,
trust·운영 정책은 API 기술명세서 9.3절을 따른다.

### 입력 (공통계약 4절: AnalysisRequest)

- `input_type`, `subject`, URL이 `[URL]`로 치환된 `body`
- `url_candidates` (표시 주소·목적지 도메인 등 HTML 정적 검사 결과 포함)

### 처리
- `get_analysis_client()`가 만든 `LocalAnalysisClient`가 `src.ui.url_candidates`로 후보를 중복 제거·우선순위화하고 상한 20개를 선택한 뒤, 상속한 URL adapter를 통해 `url_analyzer.analyze_url`을 호출
- 로컬 결과만으로 `overall_risk`, 상태와 1차 분석 응답 구성
- 사용자가 후속 질문을 하고 기본 비활성화된 기능의 모든 전제조건이 충족된 경우에만, 별도 후속 서비스가 한 페르소나·두 Responses 호출을 수행
- 첫 호출의 필수 `build_security_action_plan` Function Calling 결과를 호스트가 결정론적으로 렌더링
- 두 번째 호출의 공식-domain Web Search 및 attested·ready File Search 보조 근거를 엄격히 검증해 후속 답변에만 반영
- 실패·비활성화·전제조건 미충족 시에도 로컬 1차 분석 결과를 유지

### 출력 (공통계약 5절: AnalysisResponse)
- 로컬 종합 위험도(`overall_risk`)와 요약(`summary`)
- 로컬 위험 근거(`risk_reasons`), 대응 방법(`recommended_actions`)
- 메시지 분석(`message_analysis`), URL 분석 요약(`url_analysis_summary`)과 URL별 분석(`url_analysis`)
- 분석 한계(`limitations`), 오류 목록(`errors`)

현재 primary `AnalysisResponse`는 local-only DTO다. 호환성을 위해 `web_evidence`와 `file_evidence` 필드는 유지하지만 `LocalAnalysisClient`는 두 필드를 항상 빈 배열로 반환한다. hosted action plan·citation과 fallback은 별도 `FollowupResponse` DTO에만 공개하고, 어떤 경우에도 primary score·label·threshold·status를 바꾸지 않는다.

## 3. API 처리 흐름 (요약)

세부 호출 순서와 코드 수준 설명은 API 기술명세서 5절을 참고한다. 기능 단위로 보면 아래와 같다.

```text
AnalysisRequest
        ↓
요청 재검증 (API-F-01)
        ↓
고정 로컬 `analyze_message` / 상속 URL adapter → `url_analyzer.analyze_url` 호출 (API-F-02~03)
        ↓
overall_risk·상태·AnalysisResponse 조립 (API-F-04)
        ↓
[분석 후 사용자의 선택적 질문 + capability 준비 시]
        ↓
Responses 1: build_security_action_plan 강제 호출 (API-F-05)
        ↓
호스트의 I/O 없는 결정론적 action plan 렌더링
        ↓
Responses 2: 허용된 Web/File Search 보조 근거와 제한된 주장 (API-F-06)
        ↓
인용·출처 검증 실패 시 보조 결과 전체 폐기 (API-F-07)
```

## 4. 기능 요구사항

| ID | 기능 | 상세 내용 | 완료 조건 |
|---|---|---|---|
| API-F-01 | 요청 검증 | `AnalysisRequest`의 `schema_version`, `input_type`, `body`의 `[URL]` 치환 여부, `url_candidates` 필수 필드를 재검증한다. | 유효하지 않은 요청은 처리를 중단하고 `INVALID_INPUT` 또는 `SCHEMA_VERSION_MISMATCH` 오류를 반환한다. |
| API-F-02 | 메시지 분석 호출 | 고정된 로컬 `analyze_message(body, input_type, subject)`를 직접 호출한다. | 결과가 공통계약 6절 `message_analysis` 형식에 맞게 채워진다. |
| API-F-03 | URL 분석 호출 | `get_analysis_client()`가 만든 `LocalAnalysisClient`가 `src.ui.url_candidates`로 후보를 중복 제거·우선순위화하고 상한 20개를 선택한 뒤, 상속한 `LocalUrlAnalysisClient` adapter를 통해 고정된 로컬 `url_analyzer.analyze_url(url)`을 호출한다. | `url_analyzer.py`는 URL 추론만 수행하고 URL 실패가 다른 URL·메시지 결과에 영향을 주지 않으며 요약 값이 현재 로컬 응답과 일치한다. |
| API-F-04 | 1차 응답 조립 | 로컬 결과만으로 `overall_risk`, `summary`, `risk_reasons`, `recommended_actions`, 상태를 조립한다. | OpenAI·검색 결과는 1차 라벨·점수·임계값 또는 응답을 변경하지 않는다. |
| API-F-05 | 필수 action plan | 후속 질문에서만 첫 Responses 호출에 strict `build_security_action_plan`을 강제한다. dispatcher는 검증된 `{request_id,risk_level}`만 받고 I/O 없이 한 번 실행한다. | 1~5개 즉시 조치가 있는 host-rendered plan이 생성되며 재분류·자유 모델 문구가 없다. |
| API-F-06 | 보조 근거 | 두 번째 호출은 정확한 불투명 replay와 function output 뒤에만 Web Search 및 File Search를 제공한다. | provider trust가 먼저 성립해야 하며, 그 뒤 manifest·inventory·readiness·provenance 및 `OPENAI_VECTOR_STORE_ID`의 verified store-ID exact match가 모두 유효할 때만 File Search를 제공한다. |
| API-F-07 | 근거 승인·fallback | 인용과 claim의 URL·파일·출처 결속을 검증한다. | 불일치·중복·고아·형상 오류는 보조 주장과 인용을 전부 폐기하고 action-plan fallback만 반환한다. |
| API-F-08 | trust gate·오류 격리 | provider trust(opt-in, 키, 모델, SDK, provider contract integrity anchor)가 실패하면 Responses 호출을 만들지 않는다. | provider trust 뒤 File gate만 실패하면 File Search만 생략하고 Web-only fallback을 허용하며, 로컬 1차 분석은 계속 제공한다. |

## 5. 상태·오류 처리 (요약)

전체 판정 기준과 오류 코드 표는 API 기술명세서 7절을 참고한다. 요약하면 다음과 같다.

- `success`: 메시지 분석 또는 URL 분석 중 하나 이상이 성공한 현재 로컬 1차 응답
- `error`: 메시지와 선택된 모든 URL 분석이 실패한 현재 로컬 1차 응답

현재 `LocalAnalysisClient.status` 값은 `success`/`error` 두 가지만 사용한다. 공통계약의 `partial`은 **향후 계약 capability**이며 현재 local adapter가 emit하지 않는다. 일부 URL 실패는 `url_analysis_summary.failed_count`, URL별 결과와 `errors`에 남지만 primary 상태를 `partial`로 바꾸지 않는다. 내부 예외
메시지, OpenAI API 응답 원문, 요청 원문, API 키는 `errors[].message`를 포함한 어떤 응답 필드에도
포함하지 않는다(공통계약 4.3절, 10절).

## 6. 모델팀 연동 기준

`analyze_message`, `analyze_url` 함수의 정식 계약은 `SafeMate_모델_UI_연동_요구사항.md`에 있다. API는 다음 기준을 유지한다.

- `analyze_message(body, input_type, subject)`를 호출한다.
- `get_analysis_client()`가 만든 `LocalAnalysisClient`가 `src.ui.url_candidates`로 선택한 후보를 상속 URL adapter에 넘기고, adapter가 `url_analyzer.analyze_url(candidate["url"])`을 호출한 뒤 후보 메타데이터를 병합한다.
- 메시지 `label`은 `normal`/`phishing`/`unknown`, URL `label`은 `benign`/`suspicious`/`malicious`/`unknown`을 사용한다.
- `top_features`·`features`는 설명값이 없더라도 빈 배열로 반환한다.
- 모델별 `error`는 성공 시 `null`, 실패 시 안전한 오류 객체를 사용한다.
- 모든 결과의 `model_version`은 실제 추론에 사용한 모델 또는 모델 파일 버전을 사용한다.

## 7. 완료 기준

- `AnalysisRequest` 재검증이 공통계약 4.3절 요청 불변 조건을 모두 만족한다.
- `analyze_message`와 상속 URL adapter → `url_analyzer.analyze_url` 호출 결과가 `AnalysisResponse`에 정확히 매핑된다.
- `overall_risk.score`가 API 기술명세서의 산출 정책에 따라 생성된다.
- 후속 기능은 `SAFEMATE_OPENAI_FOLLOWUP_ENABLED`가 허용값(`1|true|yes|on`, 대소문자 무관)일 때만 검토하며 기본값은 false다.
- 두 Responses 호출은 모두 `store=False`, 재시도 없음, 최대 두 호출·한 번의 dispatcher·최대 다섯 hosted tool 호출의 상한을 지킨다.
- OpenAI provider response/file/store ID와 encrypted reasoning은 공개 응답·세션·로그에 보존하지 않는다.
- File Search는 provider trust 뒤 operator-approved nonempty manifest, attested inventory, readiness, provenance 및 `OPENAI_VECTOR_STORE_ID`의 verified store-ID exact match가 모두 유효할 때만 제공한다. 하나라도 실패하면 File Search만 fail-closed하고 Web-only 또는 action plan만 제공한다.
- provider contract integrity anchor가 실패하면 Responses 호출을 전혀 만들지 않는다. configured digest의 custody·rotation은 운영자 책임이며, configured digest는 deployment-controlled integrity anchor일 뿐 손상된 런타임에 대한 암호학적 증명이 아니다.
- live provider gate와 최대 URL·위험 임계값은 API 기술명세서 9.3절의 **결정됨** 정책을 따른다. UI 문서는 관찰 가능한 동작만 기술한다.
