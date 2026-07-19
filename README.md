# SafeMate AI

Streamlit 기반 AI 보안 비서 프로젝트입니다.

## 주요 기능

- 문자·이메일 피싱 가능성 분석
- URL 문자열 위험도 분석
- 이메일 HTML의 표시 URL과 실제 `href` 도메인 불일치 탐지
- 개인정보 탐지 및 마스킹
- OpenAI Web Search / File Search 기반 근거 제공
- 사용자 대응 방법 안내
- 1차 분석 완료 후 결과 기반 보안 비서 채팅
- 모델 반환 계약 기반 Matplotlib 위험도·특징 기여도 시각화

## 환경변수

프로젝트 루트의 `.env`에 다음 값을 설정합니다. `.env`는 Git에서 제외됩니다.

```env
OPENAI_API_KEY=발급받은_API_키
OPENAI_MODEL=gpt-5.6
OPENAI_VECTOR_STORE_ID=vs_등록된_보안문서_스토어_ID
```

`OPENAI_VECTOR_STORE_ID`가 비어 있으면 후속 채팅은 Web Search만 사용합니다.
Vector Store ID가 설정되면 File Search가 함께 활성화됩니다.

## 운영 정책

- OpenAI API는 호출 시도당 60초 타임아웃을 적용하고, 일시적 오류에 한해 최대 2회 재시도합니다.
- 종합 위험 점수는 유효한 메시지 피싱 확률과 URL 위험 점수 중 최댓값입니다. `0.4` 미만은
  `low`, `0.4` 이상 `0.7` 미만은 `medium`, `0.7` 이상은 `high`입니다.
- Web Search와 UI의 클릭 가능한 공식 출처는 코드로 검수된 국내 공공기관 HTTPS 도메인과
  그 하위 도메인으로 제한됩니다.

## 처리 단계

1. 사용자가 문자 또는 이메일을 입력합니다.
2. 채팅의 영향을 받지 않는 독립 단계에서 위험 분류와 분석을 완료합니다.
3. 확정된 분석 결과 스냅샷을 기반으로 후속 채팅을 시작합니다.
4. 후속 질문에 필요한 경우 Web Search와 File Search로 근거를 확인합니다.

입력 변경, 재분석 또는 초기화 시 기존 채팅 기록도 제거됩니다. 후속 대화는
Streamlit 세션에서 관리하며 OpenAI Responses API 요청에는 `store=false`를 적용합니다.

## 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```
