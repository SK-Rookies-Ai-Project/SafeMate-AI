# SafeMate AI

Streamlit 기반 AI 보안 비서 프로젝트입니다.

## 주요 기능

- 문자·이메일 피싱 가능성 분석
- URL 문자열 위험도 분석
- 개인정보 탐지 및 마스킹
- OpenAI Web Search / File Search 기반 근거 제공
- 사용자 대응 방법 안내

## 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

현재 저장소는 팀 개발을 위한 초기 프로젝트 구조입니다.

## 문서

- [URL 위험도 분석 모듈](docs/url_analyzer.md) — 전처리(feature/TF-IDF), DataSet/ModelBundle, 학습·튜닝, 예측 API
