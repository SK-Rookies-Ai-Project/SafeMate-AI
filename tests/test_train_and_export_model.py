"""
SMS 스팸 탐지 모델 학습 + .pkl 저장 스크립트

현재 활성 모델: TF-IDF(char_wb 2-6gram + word 1-2gram, FeatureUnion) + Naive Bayes
threshold=0.5 (기본값 채택. train_experiments.py 12-1번 전 구간 스윕에서
char+word 조합이 이 지점에서 char-only보다 FP/FN 모두 우세했음:
spam_test_master 기준 Precision=0.9032, Recall=0.70, FP=9, FN=36)

LinearSVC(+CalibratedClassifierCV), Logistic Regression, char-only(word 없이)
조합은 코드 내 코멘트 처리해둠. 다시 쓰고 싶으면 "2. 파이프라인 구성"
섹션에서 주석만 풀어서 교체 가능.

실행하면 같은 폴더에 다음 파일이 생성됩니다:
  - sms_spam_model.pkl   : 학습된 파이프라인(FeatureUnion(char+word) + 분류기) 전체
  - model_meta.json      : 라벨 의미, 학습 일시, threshold 등 메타 정보

주의: TfidfVectorizer가 sms_text_preprocessing.sms_preprocessor를 참조하므로,
sms_spam_model.pkl을 나중에 joblib.load()로 불러올 때도 sms_text_preprocessing.py가
같은 폴더(또는 import 가능한 경로)에 반드시 있어야 함.
"""

import json
import re
from datetime import datetime

import joblib
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.svm import LinearSVC

from sms_text_preprocessing import sms_preprocessor

MODEL_PATH = "sms_spam_model.pkl"
META_PATH = "model_meta.json"

# train_experiments.py 12-1번 전 구간 threshold 스윕 결과, char+word 조합
# 기준 0.5가 기본값으로 채택하기 좋은 지점으로 확인됨
# (Precision=0.9032, Recall=0.70, FP=9, FN=36)
BEST_THRESHOLD = 0.5


def normalize_template(text: str) -> str:
    """숫자는 #, 영문은 @로 치환해서 브랜드/금액/이름 등을 슬롯화.
    train_experiments.py와 동일한 정의 - GroupShuffleSplit의 그룹 키로 사용."""
    t = re.sub(r"\d+", "#", str(text))
    t = re.sub(r"[A-Za-z]+", "@", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ==========================
# 1. 데이터 로드
# ==========================
df = pd.read_csv('sms_dataset_augmented.csv')
df = df[df['channel'] == 'SMS']

X = df["text"].fillna("")
y = df["label"]

# 정규화 템플릿 기준 GroupShuffleSplit (랜덤 행 분할은 템플릿 누수를
# 일으킴 - train_experiments.py 11-4번 감사에서 확인된 문제)
groups = X.map(normalize_template)
gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, test_idx = next(gss.split(X, y, groups=groups))
X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]


# ==========================
# 2. 파이프라인 구성
# ==========================
# --- LinearSVC (코멘트 처리) ---
# 기본적으로 확률(predict_proba)을 지원하지 않아서 CalibratedClassifierCV로
# 감싸야 확률 스코어를 뽑을 수 있음. 다시 쓰려면 아래 두 줄 주석 해제 후
# clf = calibrated_clf 로 바꿔주면 됨.
# base_clf = LinearSVC(random_state=42)
# calibrated_clf = CalibratedClassifierCV(base_clf, method="sigmoid", cv=5)

# --- Logistic Regression (코멘트 처리) ---
# predict_proba를 기본 지원해서 별도 calibration 없이 바로 확률 사용 가능.
# 다시 쓰려면 아래 줄 주석 해제 후 clf = LogisticRegression(...) 로 바꿔주면 됨.
# clf = LogisticRegression(random_state=42, max_iter=1000)

# --- Naive Bayes (현재 사용 중) ---
# TF-IDF(sublinear_tf 포함)는 항상 0 이상 값이라 MultinomialNB에 바로 사용 가능.
# threshold 스윕 실험에서 이 모델 + threshold=0.9621 조합이 F1 최적으로 확인됨.
clf = MultinomialNB()

# --- char-only (코멘트 처리) ---
# word 조합 실험 전까지 쓰던 구성. 다시 쓰려면 tfidf_step을 아래 char_vectorizer로 교체.
# char_vectorizer = TfidfVectorizer(
#     analyzer="char_wb",
#     ngram_range=(2, 6),
#     sublinear_tf=True,
#     min_df=2,
#     max_df=0.95,
#     preprocessor=sms_preprocessor,
# )

# --- char + word FeatureUnion (현재 사용 중) ---
# train_experiments.py 12번 실험에서 char-only 대비 SpamTestMaster 기준
# FP/FN이 동시에 개선되는 것을 확인하고 채택함 (0.7833->0.8125 Acc,
# FP 11->9, FN 41->36 @ threshold=0.5). word는 max_features로 상한을 둬서
# char 특징을 압도하지 않도록 함.
tfidf_step = FeatureUnion([
    ("char", TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 6),
        sublinear_tf=True,
        min_df=2,
        max_df=0.95,
        preprocessor=sms_preprocessor,
    )),
    ("word", TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=2,
        max_df=0.95,
        max_features=10000,
        preprocessor=sms_preprocessor,
    )),
])

pipeline = Pipeline([
    (
        "tfidf",
        tfidf_step
    ),
    (
        "clf",
        clf
    )
])


# ==========================
# 3. 학습 + 간단 검증 (threshold=0.5 적용)
# ==========================
pipeline.fit(X_train, y_train)

y_proba = pipeline.predict_proba(X_test)[:, 1]
y_pred = (y_proba > BEST_THRESHOLD).astype(int)
print("=" * 60)
print(f"Accuracy (holdout, threshold={BEST_THRESHOLD}) :", accuracy_score(y_test, y_pred))
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
    "model": "TF-IDF(char_wb 2-6gram + word 1-2gram, FeatureUnion) + MultinomialNB",
    "trained_at": datetime.now().isoformat(timespec="seconds"),
    "train_data": "sms_dataset_augmented.csv",
    "train_rows": int(len(X)),
    "default_threshold": BEST_THRESHOLD,
    "note": "threshold=0.5(기본값). train_experiments.py 12-1번 전 구간 스윕에서 "
            "char+word 조합이 이 지점에서 char-only보다 우세함을 확인 "
            "(spam_test_master 기준 Precision=0.9032, Recall=0.70, FP=9, FN=36). "
            "실제 문구 테스트는 사용자가 직접 진행 예정.",
}
with open(META_PATH, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print(f"메타 정보 저장 완료: {META_PATH}")
