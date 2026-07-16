"""
SMS 스팸 탐지 모델 학습 + .pkl 저장 스크립트

sms_model.py에서 쓰던 것과 동일한 TF-IDF + LinearSVC 조합을 사용하되,
챗봇에서 "몇 % 확률로 스팸입니다" 같은 확신도 응답을 만들 수 있도록
CalibratedClassifierCV로 감싸서 predict_proba를 지원하게 했습니다.
(성능/임계값 튜닝은 나중에 이어서 진행하시면 되고, 지금은 배포용
파이프라인 형태만 잡는 스크립트입니다.)

실행하면 같은 폴더에 다음 파일이 생성됩니다:
  - sms_spam_model.pkl   : 학습된 파이프라인(TF-IDF + 분류기) 전체
  - model_meta.json      : 라벨 의미, 학습 일시 등 메타 정보
"""

import json
from datetime import datetime

import joblib
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

MODEL_PATH = "sms_spam_model.pkl"
META_PATH = "model_meta.json"


# ==========================
# 1. 데이터 로드 (sms_model.py와 동일한 학습 데이터)
# ==========================
df = pd.read_csv('korean_spam_ham_binary_dataset_6000row.csv')
df = df[df['channel'] == 'SMS']

X = df["text"].fillna("")
y = df["label"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)


# ==========================
# 2. 파이프라인 구성
# ==========================
# LinearSVC는 기본적으로 확률(predict_proba)을 지원하지 않아서
# CalibratedClassifierCV로 감싸서 확률 스코어를 뽑을 수 있게 함
base_clf = LinearSVC(random_state=42)
calibrated_clf = CalibratedClassifierCV(base_clf, method="sigmoid", cv=5)

pipeline = Pipeline([
    (
        "tfidf",
        TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 6),
            sublinear_tf=True,
            min_df=2,
            max_df=0.95
        )
    ),
    (
        "clf",
        calibrated_clf
    )
])


# ==========================
# 3. 학습 + 간단 검증
# ==========================
pipeline.fit(X_train, y_train)

y_pred = pipeline.predict(X_test)
print("=" * 60)
print("Accuracy (holdout) :", accuracy_score(y_test, y_pred))
print("=" * 60)
print(classification_report(y_test, y_pred))
print("Confusion Matrix")
print(confusion_matrix(y_test, y_pred))


# ==========================
# 4. 전체 데이터로 재학습 후 저장
#    (배포용 모델은 holdout 없이 가진 데이터 전부를 사용)
# ==========================
pipeline.fit(X, y)

joblib.dump(pipeline, MODEL_PATH)
print(f"\n모델 저장 완료: {MODEL_PATH}")

meta = {
    "label_meaning": {"0": "정상(ham)", "1": "스팸(spam)"},
    "model": "TF-IDF(char_wb, 2-6gram) + CalibratedClassifierCV(LinearSVC)",
    "trained_at": datetime.now().isoformat(timespec="seconds"),
    "train_rows": int(len(X)),
    "default_threshold": 0.5,
    "note": "threshold는 성능 튜닝 이후 조정 예정. 현재는 predict_proba 기본값(0.5) 사용.",
}
with open(META_PATH, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print(f"메타 정보 저장 완료: {META_PATH}")
