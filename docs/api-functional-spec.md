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

공통계약 13절 "책임 분리"는 이메일 분류 모델팀·URL 분석 모델팀과 구분해, 나머지 전체를
"프론트엔드팀" 책임으로 명시하고 있다. 이 문서는 그중 **분석 파이프라인(API) 부분**만 다루며,
Streamlit 화면·Matplotlib 시각화·분석 후 채팅 UI는 UI 담당자의 별도 문서에서 다룬다.

> 공통계약 13절의 "프론트엔드팀" 책임 범위(입력 검증부터 UI·시각화·채팅까지)가 우리 팀 안에서
> 정확히 어떻게 나뉘는지는 아직 문서로 확정되지 않았다. 이 문서는 UI 기술명세서에서 이미 UI
> 담당으로 명시된 부분(파일 파싱, 화면, 시각화, 채팅)을 제외한 나머지를 API 담당 범위로 가정한다.

### 입력 (공통계약 4절: AnalysisRequest)

- `input_type`, `subject`, URL이 `[URL]`로 치환된 `body`
- `url_candidates` (표시 주소·목적지 도메인 등 HTML 정적 검사 결과 포함)

### 처리

- 요청 재검증(스키마 버전, 필수 값, 요청 불변 조건 준수 여부)
- `analyze_message(body)` 직접 호출
- `url_candidates` 각각에 대해 `analyze_url(candidate)` 직접 호출
- `url_analysis_summary` 집계(후보 수, 분석 완료 수, 제외 수, 실패 수)
- Responses API의 `web_search`·`file_search` 도구로 근거 수집
- 근거를 `web_evidence`·`file_evidence`로 정규화
- 로컬 모델 결과와 근거를 바탕으로 `summary`·`risk_reasons`·`recommended_actions` 생성
- `overall_risk` 산출과 상태(`success`/`partial`/`error`) 판정

### 출력 (공통계약 5절: AnalysisResponse)

- 종합 위험도(`overall_risk`)와 요약(`summary`)
- 위험 근거(`risk_reasons`), 대응 방법(`recommended_actions`)
- 메시지 분석(`message_analysis`), URL 분석 요약(`url_analysis_summary`)과 URL별 분석(`url_analysis`)
- 공식 출처(`web_evidence`, `file_evidence`)
- 분석 한계(`limitations`), 오류 목록(`errors`)

## 3. API 처리 흐름 (요약)

세부 호출 순서와 코드 수준 설명은 API 기술명세서 5절을 참고한다. 기능 단위로 보면 아래와 같다.

```text
AnalysisRequest
        ↓
요청 재검증 (API-F-01)
        ↓
analyze_message() 직접 호출 (API-F-02)
        ↓
url_candidates별 analyze_url() 직접 호출, url_analysis_summary 집계 (API-F-03)
        ↓
Responses API: web_search / file_search 도구 호출 (API-F-04)
        ↓
web_evidence / file_evidence 정규화 (API-F-05)
        ↓
summary / risk_reasons / recommended_actions 생성 (API-F-06)
        ↓
overall_risk 산출, 상태·오류 판정 (API-F-07)
        ↓
AnalysisResponse 검증 후 반환 (API-F-08)
```

## 4. 기능 요구사항

| ID | 기능 | 상세 내용 | 완료 조건 |
|---|---|---|---|
| API-F-01 | 요청 검증 | `AnalysisRequest`의 `schema_version`, `input_type`, `body`의 `[URL]` 치환 여부, `url_candidates` 필수 필드를 재검증한다. | 유효하지 않은 요청은 처리를 중단하고 `INVALID_INPUT` 또는 `SCHEMA_VERSION_MISMATCH` 오류를 반환한다. |
| API-F-02 | 메시지 분석 호출 | `analyze_message(body)`를 직접 호출한다. | 결과가 공통계약 6절 `message_analysis` 형식에 맞게 채워진다. |
| API-F-03 | URL 분석 호출 | `url_candidates` 각 항목에 대해 `analyze_url(candidate)`를 직접 호출하고 `url_analysis_summary`를 집계한다. | 하나의 URL 실패가 다른 URL 결과나 `message_analysis`에 영향을 주지 않으며, `url_analysis_summary`의 네 값이 공통계약 7절 정의와 일치한다. |
| API-F-04 | 근거 검색 | Responses API가 필요 시 `web_search`·`file_search` 도구를 호출하여 관련 공식 자료 및 최신 사례를 검색한다. | 검색 실패 시에도 이미 확보한 `message_analysis`·`url_analysis` 결과는 유지되며, Search 호출 여부는 GPT가 판단한다. |
| API-F-05 | 근거 정규화 | 검색 결과를 `web_evidence`·`file_evidence` 형식으로 정규화한다. | API 기술명세서 6절 규칙에 따라 정규화되며, 의심 URL과 검색 근거 URL이 서로 섞이지 않는다. |
| API-F-06 | 요약·근거 생성 | Responses API가 로컬 모델 결과와 검색 근거를 바탕으로 `summary`, `risk_reasons`, `recommended_actions`를 생성한다. | 생성된 결과가 `AnalysisResponse` 계약에 맞게 반환된다. |
| API-F-07 | 종합 위험도·상태 판정 | `overall_risk`를 API 기술명세서의 산출 정책에 따라 생성하고, `status`를 판정하며 `errors` 배열을 구성한다. | 필수 메시지 분석 실패 시 `error`, 일부 URL·검색만 실패 시 `partial`로 정확히 구분된다. |
| API-F-08 | 응답 검증·반환 | 조립된 결과가 `AnalysisResponse` 계약을 만족하는지 검증한 뒤 반환한다. | 계약 검증을 통과한 응답만 반환하며, 실패 시 `RESPONSE_VALIDATION_FAILED`를 반환하고 내부 예외 정보는 노출하지 않는다. |

## 5. 상태·오류 처리 (요약)

전체 판정 기준과 오류 코드 표는 API 기술명세서 7절을 참고한다. 요약하면 다음과 같다.

- `success`: 메시지 분석과 모든 URL 분석이 성공한 경우
- `partial`: 메시지 분석은 성공했지만 일부 URL 분석 또는 검색 기능이 실패한 경우
- `error`: 메시지 분석 자체가 실패했거나 전체 분석이 불가능한 경우

`status` 값은 공통계약 5.1절과 동일하게 `success`/`partial`/`error` 세 가지만 사용한다. 내부 예외
메시지, OpenAI API 응답 원문, 요청 원문, API 키는 `errors[].message`를 포함한 어떤 응답 필드에도
포함하지 않는다(공통계약 4.3절, 10절).

## 6. 모델팀 확인 체크리스트

`analyze_message`, `analyze_url` 함수의 정식 계약은 `SafeMate_모델_UI_연동_요구사항.md`에 있다. API
기술명세서 8절에는 그 문서가 공유되기 전까지의 초안을 정리했으며, 아래 항목을 모델팀과 확인해
확정해야 한다.

- [ ] `SafeMate_모델_UI_연동_요구사항.md` 기준으로 API 초안(8절)과 실제 반환 필드·자료형이
      일치하는가
- [ ] `label` enum 값(메시지: `normal`/`phishing`/`unknown`, URL: `benign`/`suspicious`/`malicious`/
      `unknown`)이 공통계약과 정확히 일치하는가
- [ ] `top_features`·`features`가 항상 배열로 오는지(빈 배열 vs `null`)
- [ ] 모델 실패 시 예외를 던지는지, `error` 필드로 실패를 알리는지
- [ ] `model_version` 표기 규칙과 버전 변경 시 공지 절차

## 7. 완료 기준

- `AnalysisRequest` 재검증이 공통계약 4.3절 요청 불변 조건을 모두 만족한다.
- `analyze_message`, `analyze_url`이 직접 호출되고 결과가 `AnalysisResponse`에 정확히 매핑된다.
- `overall_risk.score`가 API 기술명세서의 산출 정책에 따라 생성된다.
- File Search는 호출당 최대 5개의 관련 결과를 반환하고, Web Search는 필요 시 Responses API를 통해 호출되도록 구현한다.
- 정상·부분(`partial`)·전체 실패(`error`) 3가지 상황에서 각각 예상되는 응답 형태를 UI 팀과 합의한다.
- API 키, 내부 예외, OpenAI 응답 원문, 요청 원문이 노출되지 않는다.
- 모델 함수 계약이 `SafeMate_모델_UI_연동_요구사항.md`와 일치하도록 최종 반영된다.
- Timeout(최대 60초), Retry(최대 2회) 정책이 API 구현에 반영된다.
