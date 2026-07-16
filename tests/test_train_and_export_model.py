
import json
from datetime import datetime

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

MODEL_PATH = "sms_spam_model.pkl"
META_PATH = "model_meta.json"

# 모델 3종 threshold 스윕 + PR curve 실험에서
# Naive Bayes 기준 F1이 최적이었던 지점 (모든 결과 중 최선으로 판단)
BEST_THRESHOLD = 0.9621


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



clf = MultinomialNB()

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
        clf
    )
])


# ==========================
# 3. 학습 + 간단 검증 (threshold=0.9621 적용)
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
    "model": "TF-IDF(char_wb, 2-6gram) + MultinomialNB",
    "trained_at": datetime.now().isoformat(timespec="seconds"),
    "train_rows": int(len(X)),
    "default_threshold": BEST_THRESHOLD,
    "note": "threshold=0.9621은 spam_test_master 기반 PR curve 실험에서 F1 최적으로 확인된 값.",
}
with open(META_PATH, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print(f"메타 정보 저장 완료: {META_PATH}")
