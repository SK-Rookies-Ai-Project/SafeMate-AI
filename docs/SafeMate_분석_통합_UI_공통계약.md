# SafeMate 분석 통합·UI 공통 계약

## 1. 문서 목적

실제 로컬 분석 파이프라인과 향후 HTTP API가 동일한 요청과 응답 구조를 사용하도록 계약을 고정한다.

| 문서 | 범위 |
|---|---|
| `SafeMate_모델_UI_연동_요구사항.md` | 이메일 분류 모델과 URL 분석 모델이 각각 반환할 값 |
| `SafeMate_분석_통합_UI_공통계약.md` | 두 모델 결과, 검색 근거, 오류를 통합해 UI에 전달할 전체 결과 |

## 2. 전체 호출 구조

```text
Streamlit UI
→ AnalysisClient.analyze(AnalysisRequest)
→ 메시지 분류 모델 직접 호출
→ URL 분석 모델 반복 직접 호출
→ Web Search / File Search 근거 취합
→ AnalysisResponse 반환
→ UI 시각화 및 후속 채팅
```

UI는 `LocalAnalysisClient` 또는 HTTP API 구현 여부와 관계없이 동일한 `AnalysisRequest`와 `AnalysisResponse`만 사용한다. OpenAI는 로컬 모델 호출 여부나 모델 입력을 결정하지 않으며, 검색 근거 취합과 사용자용 설명 생성에만 사용한다.

## 3. 공통 인터페이스

```python
from typing import Protocol


class AnalysisClient(Protocol):
    def analyze(self, payload: dict) -> dict:
        ...
```

구현체:

```text
LocalAnalysisClient  실제 모델 함수를 직접 호출하는 구현
ApiAnalysisClient    향후 HTTP 분석 API를 호출하는 구현
```

## 4. AnalysisRequest 계약

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

### 4.1 최상위 필드

| 필드 | 타입 | 필수 | 규칙 |
|---|---|---|---|
| `schema_version` | `str` | 필수 | 현재 버전 `1.0` |
| `request_id` | `str` | 필수 | 요청별 고유 식별자 |
| `input_type` | `str` | 필수 | `sms` 또는 `email` |
| `subject` | `str \| null` | 필수 | SMS는 `null`, 이메일은 제목 또는 `null` |
| `body` | `str` | 필수 | URL이 `[URL]`로 치환된 모델 입력용 본문 |
| `url_candidates` | `array` | 필수 | 추출된 URL 후보 목록, URL이 없으면 빈 배열 |

### 4.2 URL 후보 필드

| 필드 | 타입 | 필수 | 규칙 |
|---|---|---|---|
| `url` | `str` | 필수 | 추출된 URL 원문 |
| `source_type` | `str` | 필수 | `text`, `href`, `image_src` 중 하나 |
| `input_index` | `int` | 필수 | 추출 순서, 0 이상 |
| `displayed_url` | `str` | 선택 | HTML 링크에 표시된 URL |
| `displayed_domain` | `str` | 선택 | 표시 URL의 정규화 도메인 |
| `destination_domain` | `str` | 선택 | 실제 `href` 목적지 도메인 |
| `display_href_mismatch` | `bool` | 선택 | 표시 도메인과 목적지 도메인의 불일치 여부 |
| `signals` | `array[str]` | 선택 | HTML 정적 검사에서 발견된 위험 신호 |

### 4.3 요청 불변 조건

1. `body`에 URL 원문을 포함하지 않고 `[URL]`로 치환한다.
2. URL 원문은 `url_candidates`에 보존한다.
3. URL 후보는 외부 접속 없이 문자열과 HTML 속성만으로 추출한다.
4. 모델 또는 LLM이 요청에 없던 URL을 추가할 수 없다.
5. 요청 원문과 API 키를 로그에 기록하지 않는다.

## 5. AnalysisResponse 계약

```json
{
  "schema_version": "1.0",
  "request_id": "analysis-a1b2c3d4",
  "input_type": "email",
  "status": "success",
  "overall_risk": {"level": "high", "score": 0.84},
  "summary": "계정 인증을 요구하며 표시 주소와 실제 연결 주소가 다릅니다.",
  "risk_reasons": [
    "개인정보 입력을 요구합니다.",
    "이메일에 표시된 주소와 실제 연결 주소가 다릅니다."
  ],
  "recommended_actions": [
    "이메일 속 URL을 열지 마세요.",
    "발신 기관의 공식 채널에서 내용을 확인하세요."
  ],
  "message_analysis": {},
  "url_analysis_summary": {},
  "url_analysis": [],
  "web_evidence": [],
  "file_evidence": [],
  "limitations": [],
  "errors": []
}
```

### 5.1 최상위 필드

| 필드 | 타입 | 필수 | 규칙 |
|---|---|---|---|
| `schema_version` | `str` | 필수 | 요청과 동일한 지원 버전 |
| `request_id` | `str` | 필수 | 요청의 `request_id`와 동일 |
| `input_type` | `str` | 필수 | 요청의 `input_type`과 동일 |
| `status` | `str` | 필수 | `success`, `partial`, `error` 중 하나 |
| `overall_risk` | `object` | 필수 | 종합 위험 수준과 점수 |
| `summary` | `str` | 필수 | 사용자용 분석 요약 |
| `risk_reasons` | `array[str]` | 필수 | 주요 위험 근거, 최대 5개 권장 |
| `recommended_actions` | `array[str]` | 필수 | 우선순위가 있는 대응 행동, 최대 5개 권장 |
| `message_analysis` | `object` | 필수 | 이메일·문자 분류 모델 결과 |
| `url_analysis_summary` | `object` | 필수 | URL 처리 개수 요약 |
| `url_analysis` | `array` | 필수 | URL별 분석 결과 |
| `web_evidence` | `array` | 필수 | Web Search 근거, 없으면 빈 배열 |
| `file_evidence` | `array` | 필수 | File Search 근거, 없으면 빈 배열 |
| `limitations` | `array` | 필수 | 분석 한계 목록 |
| `errors` | `array` | 필수 | 부분 또는 전체 실패 목록 |

### 5.2 overall_risk

```json
{"level": "high", "score": 0.84}
```

| 필드 | 규칙 |
|---|---|
| `level` | `low`, `medium`, `high`, `unknown` 중 하나 |
| `score` | `0.0`~`1.0`, 산출 불가 시 `null` |

종합 위험 수준 계산은 UI가 아니라 분석 파이프라인이 담당한다.

## 6. message_analysis 계약

```json
{
  "status": "success",
  "label": "phishing",
  "phishing_probability": 0.84,
  "signals": ["개인정보 입력 요구", "긴급성을 강조하는 표현"],
  "top_features": [
    {"name": "비밀번호", "value": 1.0, "contribution": 0.31}
  ],
  "model_version": "message-v1",
  "error": null
}
```

| 필드 | 필수 | 규칙 |
|---|---|---|
| `status` | 필수 | `success` 또는 `error` |
| `label` | 필수 | `normal`, `phishing`, `unknown` |
| `phishing_probability` | 필수 | `0.0`~`1.0`, 판단 불가 시 `null` |
| `signals` | 필수 | 사람이 이해할 수 있는 분류 근거 |
| `top_features` | 필수 | 설명값이 없으면 빈 배열 |
| `model_version` | 필수 | 실제 모델 또는 모델 파일 버전 |
| `error` | 필수 | 성공 시 `null`, 실패 시 안전한 오류 객체 |

## 7. url_analysis_summary 계약

```json
{
  "candidate_count": 3,
  "analyzed_count": 2,
  "omitted_url_count": 1,
  "failed_count": 0
}
```

| 필드 | 규칙 |
|---|---|
| `candidate_count` | 중복 제거 후 URL 후보 개수 |
| `analyzed_count` | 모델 호출을 시도한 URL 개수(성공과 실패 포함) |
| `omitted_url_count` | 최대 분석 개수 제한으로 호출하지 않은 URL 개수 |
| `failed_count` | 모델 호출을 시도했으나 실패한 URL 개수 |

다음 불변식을 만족해야 한다.

```text
candidate_count = analyzed_count + omitted_url_count
failed_count <= analyzed_count
```

## 8. url_analysis 항목 계약

```json
{
  "url": "https://evil.example/login",
  "input_indexes": [0, 2],
  "occurrence_count": 2,
  "source_types": ["text", "href"],
  "status": "success",
  "label": "suspicious",
  "risk_score": 0.78,
  "signals": [
    "로그인 경로 포함",
    "표시 주소와 실제 연결 도메인이 다릅니다."
  ],
  "features": [
    {
      "name": "URL 길이",
      "raw_value": 83,
      "normalized_value": 0.72,
      "contribution": 0.18
    }
  ],
  "displayed_url": "https://official.example/login",
  "displayed_domain": "official.example",
  "destination_domain": "evil.example",
  "display_href_mismatch": true,
  "model_version": "url-v1",
  "error": null
}
```

| 필드 | 필수 | 규칙 |
|---|---|---|
| `url` | 필수 | 분석한 URL 원문 |
| `input_indexes` | 필수 | 중복 URL이 발견된 원본 위치 목록 |
| `occurrence_count` | 필수 | URL 발견 횟수 |
| `source_types` | 필수 | `text`, `href`, `image_src` 조합 |
| `status` | 필수 | `success` 또는 `error` |
| `label` | 필수 | `benign`, `suspicious`, `malicious`, `unknown` |
| `risk_score` | 필수 | `0.0`~`1.0`, 판단 불가 시 `null` |
| `signals` | 필수 | 모델과 정적 HTML 검사 위험 신호를 통합한 목록 |
| `features` | 필수 | 설명값이 없으면 빈 배열 |
| `displayed_*` | 선택 | HTML 링크 표시 주소 관련 메타데이터 |
| `display_href_mismatch` | 필수 | HTML 링크가 아니면 `false` |
| `model_version` | 필수 | 실제 모델 또는 모델 파일 버전 |
| `error` | 필수 | 성공 시 `null`, 실패 시 안전한 오류 객체 |

URL 중복 제거, 우선순위 지정, 최대 20개 선택, HTML 정적 신호 병합은 분석 파이프라인이 담당한다. URL 모델에는 각 후보의 `url` 문자열만 전달한다.

## 9. 검색 근거 계약

### 9.1 web_evidence

```json
{
  "title": "스미싱 피해 예방 안내",
  "organization": "공식 기관명",
  "published_at": "2026-07-01",
  "summary": "스미싱 피해 예방과 신고 방법을 안내합니다.",
  "url": "https://official.example/security-guide"
}
```

| 필드 | 필수 |
|---|---|
| `title` | 필수 |
| `organization` | 필수 |
| `published_at` | 선택 |
| `summary` | 선택 |
| `url` | 필수, 검증된 `http` 또는 `https` 주소 |

### 9.2 file_evidence

```json
{
  "title": "스미싱 대응 지침",
  "organization": "공식 기관명",
  "filename": "smishing_guide.pdf",
  "page": 12,
  "excerpt": "의심 링크를 클릭하지 않고 공식 채널을 통해 확인한다.",
  "external_url": null
}
```

| 필드 | 필수 |
|---|---|
| `title` | 필수 |
| `organization` | 필수 |
| `filename` | 필수 |
| `page` | 선택 |
| `excerpt` | 선택 |
| `external_url` | 선택, 검증된 주소 또는 `null` |

의심 URL과 검색 근거 URL을 혼합하지 않는다. 의심 URL은 클릭 가능한 링크로 표시하지 않는다.

## 10. 한계와 오류 계약

### 10.1 limitation

```json
{
  "code": "MODEL_NOT_DETERMINISTIC",
  "message": "분석 결과만으로 실제 피싱 여부를 확정할 수 없습니다."
}
```

### 10.2 error

```json
{
  "component": "url_analysis",
  "code": "URL_MODEL_FAILED",
  "message": "일부 URL을 분석하지 못했습니다.",
  "retryable": true,
  "item_index": 1
}
```

모델별 `error`도 성공 시 `null`, 실패 시 다음 형태의 객체를 사용한다.

```json
{
  "code": "MODEL_INFERENCE_FAILED",
  "message": "모델 분석에 실패했습니다.",
  "retryable": false
}
```

오류 응답에는 원문, API 키, 내부 파일 경로, 스택트레이스를 포함하지 않는다.

## 11. 상태 결정 규칙

| 상황 | `status` |
|---|---|
| 필수 메시지 분석과 모든 필수 URL 분석 성공 | `success` |
| 메시지 분석 성공, 일부 URL 또는 검색 기능 실패 | `partial` |
| 필수 메시지 분석 실패 또는 전체 분석 불가 | `error` |

부분 실패 시 성공한 메시지·URL 분석 결과를 유지한다.

## 12. 향후 HTTP API 적용 시 규칙

로컬 `AnalysisClient` 계약을 HTTP 전송 형식으로 그대로 감싼다.

```text
POST /analysis
Content-Type: application/json
```

요청 본문은 `AnalysisRequest`, 성공 응답 본문은 `AnalysisResponse`를 사용한다.

| HTTP 상태 | 사용 조건 |
|---|---|
| `200` | 분석 성공 또는 부분 성공 |
| `400` | 요청 스키마·입력 검증 실패 |
| `413` | 업로드 크기 제한 초과 |
| `500` | 복구할 수 없는 내부 오류 |

모델의 개별 실패는 가능한 경우 HTTP 500으로 변환하지 않고 `AnalysisResponse.status="partial"`과 `errors`에 기록한다.

## 13. 책임 분리

| 담당 | 책임 |
|---|---|
| 이메일 메시지 분류 모델팀 | `analyze_message()` 구현, 학습 완료 모델, 전처리기, 모델 버전, 테스트 제공 |
| URL 분석 모델팀 | `analyze_url()` 구현, 학습 완료 모델, 특징 추출기, 모델 버전, 테스트 제공 |
| 분석 파이프라인/API팀 | 입력 재검증, 두 모델 직접 호출, URL 중복 제거·선정, 결과 통합, 종합 위험 수준 산출, 오류·부분 실패 처리, OpenAI·검색 연동 |
| UI팀 | 입력 처리와 미리보기, `AnalysisClient` 호출, Streamlit UI, Matplotlib 시각화, 분석 후 채팅 UI |

모델팀은 정의된 추론 함수와 결과 계약까지만 책임진다. 분석 파이프라인과 UI는 모델 결과를 변경하거나 임의의 특징·기여도를 생성하지 않는다.

## 14. 완료 기준

- 로컬 분석 구현과 HTTP API 구현이 동일한 계약 테스트를 통과한다.
- 모든 응답을 `json.dumps(result, allow_nan=False)`로 직렬화할 수 있다.
- 필수 필드와 enum이 스키마와 일치한다.
- URL 없음과 부분 실패 시에도 UI가 렌더링된다.
- 실제 모델 전환 시 UI 코드 변경 없이 `AnalysisClient` 구현만 교체할 수 있다.
