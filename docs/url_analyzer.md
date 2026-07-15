# URL 위험도 분석 모듈

URL 배열을 입력받아 전처리(feature 추출 / TF-IDF) 후 학습된 모델로
위험/안전을 판정하는 모듈. `src/analyzers/url_analyzer.py`가 진입점이다.

## 프로그램 흐름

```
URL 링크 배열
  → 전처리 (유형1: feature 추출 | 유형2: TF-IDF)
  → DataSet
  → 학습된 모델 (xgboost / randomforest, 하이퍼파라미터 튜닝)
  → {링크: "위험"/"안전"} 딕셔너리
```

## 디렉터리 구조

```
src/analyzers/
├── url_analyzer.py     # 메인 진입 파일 (외부는 이것만 import)
└── url/
    ├── constants.py    # 데이터 경로, 라벨, 민감 키워드
    ├── schemas.py      # DataSet, ModelBundle
    ├── features.py     # URL 정규화/전처리/특징 추출 (유형1 + 유형2)
    ├── training.py     # CSV 로딩, 모델 학습, 하이퍼파라미터 튜닝
    └── prediction.py   # 예측, 위험 점수, 판단 근거 생성
scripts/
└── train_url_model.py  # 전체 데이터 본 학습 스크립트
models/                 # 학습된 ModelBundle(.joblib) 저장 위치
tests/
├── test_url_features.py
└── test_url_ml.py
```

## 빠른 시작 (실사용)

```python
from src.analyzers.url_analyzer import analyze_urls, analyze_urls_detail

# models/url_feature_model.joblib 을 자동 로딩
result = analyze_urls([
    "https://www.naver.com/",
    "http://211.239.150.212/secure-login/verify.php?acc=x1",
])
# {"https://www.naver.com/": "안전",
#  "http://211.239.150.212/secure-login/verify.php?acc=x1": "위험"}

# 디버그/UI용 상세 결과
detail = analyze_urls_detail(["http://211.239.150.212/secure-login/..."])
# [{"url": ..., "label": "악성", "verdict": "위험", "risk_score": 0.97,
#   "reasons": ["피싱에 자주 쓰이는 단어 포함: secure, login", ...]}]
```

## 전처리

### 유형1 — lexical feature 추출 (`features.py`)

`build_url_dataset(urls)` → 학습 데이터 All.csv(ISCX-URL-2016)와 동일한
79개 컬럼의 DataFrame. 도메인/경로/파일명/확장자/쿼리 컴포넌트별
길이·토큰·숫자/문자/기호 개수·비율·엔트로피를 계산한다.

All.csv에서 관측한 규칙을 그대로 따른다:

| 규칙 | 내용 |
|---|---|
| `tld` | TLD 문자열이 아니라 **TLD 길이(숫자)** |
| `Entropy_*` | Shannon entropy를 log2(길이)로 나눈 정규화값(0~1). 길이 0 → -1, 길이 1 → NaN |
| `NumberRate_Extension` | 확장자 없으면 NaN (다른 `NumberRate_*`는 -1) |
| `avgpathtokenlen` | 경로 토큰 없으면 NaN |
| `isPortEighty` | 포트 80 명시 → 0, 그 외 → -1 |
| `ISIpAddressInDomainName` | 학습 데이터 전체가 -1인 죽은 feature → 상수 -1 |
| 그 외 미정의 값 | -1 |

모델 입력 전에는 `clean_feature_matrix()`로 NaN/±inf를 -1로 치환한다
(NaN을 못 받는 모델 대비). `ModelBundle.transform()`이 자동으로 처리한다.

> **주의**: All.csv를 만든 원본 추출 도구는 비공개라 일부 feature
> (`ArgLen`, `spcharUrl`, `delimeter_*`, `charcompace` 등)는 표준 정의로
> 근사했다. 따라서 **All.csv로 학습한 모델은 이 모듈의 추론 feature와
> 정의가 미묘하게 어긋나** 실제 URL에서 오탐이 늘어난다.
> 실서비스 모델은 반드시 raw URL(url_binary_dataset.csv)에서 이 모듈로
> feature를 추출해 학습할 것 (train/serve 일치). `scripts/train_url_model.py`가
> 그 절차다.

### 유형2 — TF-IDF (`features.py`)

```python
ds, vectorizer = training.make_tfidf_dataset(urls, labels)   # 학습: fit
bundle = training.train_model(ds, kind="tfidf", vectorizer=vectorizer)
# 추론 시엔 bundle.transform(urls)이 vectorizer.transform을 재사용
```

기본 벡터라이저: 문자 n-gram(`char_wb`, 3~5), max_features=100,000.
`build_tfidf_vectorizer(**overrides)`로 변경 가능.

## 클래스

### DataSet (`schemas.py`)

전처리된 데이터셋. 속성: `x`(feature 행렬), `y`(라벨, 추론 시 None),
`n_features`, `name`, `random_state`. `split(test_size)`로 층화
train/test 분할.

### ModelBundle (`schemas.py`)

학습된 모델 + 전처리기 + 메타데이터 묶음. **추론 시 학습과 동일한
전처리를 보장**하는 단위로, joblib 파일 하나로 저장/배포한다.

| 필드 | 내용 |
|---|---|
| `model` | 학습된 sklearn/xgboost 모델 |
| `kind` | `"feature"` 또는 `"tfidf"` — `transform()`의 전처리 결정 |
| `vectorizer` | kind="tfidf"일 때 fit된 TfidfVectorizer |
| `feature_names` | kind="feature"일 때 컬럼 순서 |
| `label_encoder` | y 인코딩에 쓴 LabelEncoder (예측을 원본 라벨로 복원) |
| `params`, `metrics` | 하이퍼파라미터, holdout 평가 지표 |

메서드: `transform(urls)`, `predict_labels(urls)`, `predict_proba(urls)`,
`save(path)`, `ModelBundle.load(path)`.

## 학습 (`training.py`)

```python
from src.analyzers.url import training

# All.csv 로딩 (feature 79개 + 라벨 5종)
ds = training.load_feature_csv()

# raw URL → feature DataSet (권장 경로)
urls, labels = training.load_url_csv(nrows=100_000)
ds = training.make_feature_dataset(urls, labels)

# 모델 선택식 학습 (+ 튜닝)
bundle = training.train_model(
    ds,
    model_type="xgboost",        # MODEL_FACTORIES: randomforest | xgboost
    tune=True,                   # RandomizedSearchCV
    tune_kwargs=dict(n_iter=20, cv=3),
)
bundle.save("models/my_model.joblib")
```

- 모델 추가는 `training.MODEL_FACTORIES`에 팩토리 함수 등록 +
  `DEFAULT_PARAM_DISTRIBUTIONS`에 탐색 공간 추가.
- `train_model`은 holdout(기본 20%)으로 지표를 계산한 뒤 전체 데이터로
  재학습한 모델을 번들에 담는다.

## 본 학습 (전체 데이터)

```bash
.venv/bin/python scripts/train_url_model.py                 # 전체 17.4M행
.venv/bin/python scripts/train_url_model.py --per-class 100000  # 빠른 시험
```

절차: 전량 병렬 feature 추출(32코어 기준 수 분) → 층화 5% holdout →
20만 건 서브샘플로 RandomizedSearchCV(n_iter=12, cv=3, f1_macro) →
최적 파라미터로 본 학습(xgboost=전체, randomforest=2M 샘플·트리 메모리
한계) → holdout 평가 → `models/url_feature_{모델}.joblib` 저장, 최고
성능 모델을 `models/url_feature_model.joblib`(기본 경로)에 복사.

### 본 학습 결과 (2026-07-14, url_binary_dataset.csv 전체)

17,378,255행 전량 feature 추출(32코어 병렬, 59초) 후 튜닝·학습.
holdout은 층화 5%(868,913행), 튜닝은 RandomizedSearchCV(n_iter=12, cv=3).

| 모델 | 학습 행 수 | accuracy | f1_macro | ROC-AUC | 학습 시간 |
|---|---|---|---|---|---|
| **xgboost** (기본 모델로 채택) | 16,509,342 (전체) | **0.925** | **0.913** | **0.964** | CPU 87s / GPU 21s |
| randomforest | 2,000,000 (샘플) | 0.917 | 0.904 | 0.954 | 65s (CPU 전용) |

- xgboost 최적 파라미터: n_estimators=300, max_depth=10, learning_rate=0.3,
  subsample=1.0, colsample_bytree=0.85
- randomforest 최적 파라미터: n_estimators=200, min_samples_split=10,
  max_features="sqrt", max_depth=None
- 저장 위치: `models/url_feature_xgboost.joblib`,
  `models/url_feature_randomforest.joblib`, 기본 경로
  `models/url_feature_model.joblib`(=xgboost)

sanity check (xgboost): naver.com/google.com 홈 → 안전, IP+피싱 URL →
위험(risk 1.00). 단 `google.com/search?q=hello`처럼 **쿼리가 붙은 짧은
URL은 위험으로 오탐**하는 경향이 있다 — 학습 데이터의 악성 URL 상당수가
`?ref=` 류 쿼리 패턴이기 때문. 실서비스 전에 정상 쿼리 URL을 보강해
재학습하거나 위험 판정 임계값(risk_score) 조정을 검토할 것.

### GPU 가속

xgboost는 `--gpu` 플래그로 CUDA 학습 가능 (`device="cuda"`). 전체 데이터
본 학습 기준 87초(CPU 32코어) → 21초(RTX 5070 Ti)로 약 4배 빠르고 지표는
동일하다. scikit-learn RandomForest는 GPU를 지원하지 않는다(대안: RAPIDS
cuML). 시험 실행 시에는 `--tag` 로 저장 파일명을 분리해 기본 모델을
덮어쓰지 않도록 한다.

```bash
.venv/bin/python scripts/train_url_model.py --gpu
.venv/bin/python scripts/train_url_model.py --per-class 20000 --tag smoke  # 시험
```

## 판정 정책

- 모델 예측 라벨이 `BENIGN_LABELS`(benign/정상)에 없으면 "위험".
- **http/https 외 명시적 스킴**(`javascript:`, `data:`, `ftp:` 등)은 모델
  판정과 무관하게 **무조건 "위험"** (risk_score 1.0, 근거에 스킴 표기).
  `example.com:8080/path` 같은 호스트:포트는 스킴으로 오인하지 않는다.
- `risk_score` = 1 − P(정상 라벨). 확률 미지원 모델이면 위험 예측 시 1.0.

## 데이터

`/mnt/xf1230/SK/Module1/data/` (저장소 외부):

| 파일 | 내용 |
|---|---|
| `All.csv` | ISCX-URL-2016 feature 79개 + 라벨 5종(Defacement/benign/phishing/malware/spam), 36,707행. raw URL 없음 |
| `url_binary_dataset.csv` | raw URL + status(악성/정상), 17,378,255행 (악성 5.8M → 정상 11.6M 순으로 **클래스 정렬됨**). URL이 작은따옴표로 감싸져 있고 BOM 존재(`encoding="utf-8-sig"`) |

## 테스트

```bash
.venv/bin/python -m pytest tests/test_url_features.py tests/test_url_ml.py
```

- `test_url_features.py`: feature 추출이 All.csv 규칙(-1/NaN, 정규화
  엔트로피, tld 길이 등)을 지키는지 검증
- `test_url_ml.py`: DataSet 명세, 모델 레지스트리, feature/TF-IDF 학습,
  튜닝, 저장/로딩, `{링크: 위험/안전}` 출력 형식 검증
