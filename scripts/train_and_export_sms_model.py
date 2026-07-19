"""Train and export the production SMS spam model."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import FeatureUnion, Pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analyzers.sms_preprocessing import sms_preprocessor


DATA_PATH = PROJECT_ROOT / "data" / "raw" / "sms_dataset_augmented.csv"
MODELS_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODELS_DIR / "sms_spam_model.pkl"
META_PATH = MODELS_DIR / "sms_model_meta.json"
BEST_THRESHOLD = 0.5


def normalize_template(text: str) -> str:
    """Normalize variable slots for leakage-resistant group splitting."""
    normalized = re.sub(r"\d+", "#", str(text))
    normalized = re.sub(r"[A-Za-z]+", "@", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def build_pipeline() -> Pipeline:
    """Build the feature/SMS char+word Naive Bayes pipeline."""
    features = FeatureUnion(
        [
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(2, 6),
                    sublinear_tf=True,
                    min_df=2,
                    max_df=0.95,
                    preprocessor=sms_preprocessor,
                ),
            ),
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                    min_df=2,
                    max_df=0.95,
                    max_features=10_000,
                    preprocessor=sms_preprocessor,
                ),
            ),
        ]
    )
    return Pipeline([("tfidf", features), ("clf", MultinomialNB())])


def load_sms_data(data_path: Path = DATA_PATH) -> tuple[pd.Series, pd.Series]:
    """Load the augmented SMS rows used by the feature branch."""
    data = pd.read_csv(data_path)
    sms_rows = data.loc[data["channel"].astype(str).str.upper() == "SMS"].copy()
    sms_rows = sms_rows.dropna(subset=["text", "label"])
    if sms_rows.empty:
        raise ValueError("SMS training data is empty")
    return sms_rows["text"].astype(str), sms_rows["label"].astype(int)


def train_and_export() -> None:
    """Evaluate with group split, refit on all rows, and export the model."""
    texts, labels = load_sms_data()
    groups = texts.map(normalize_template)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_indices, test_indices = next(splitter.split(texts, labels, groups=groups))

    pipeline = build_pipeline()
    pipeline.fit(texts.iloc[train_indices], labels.iloc[train_indices])
    probabilities = pipeline.predict_proba(texts.iloc[test_indices])[:, 1]
    predictions = (probabilities >= BEST_THRESHOLD).astype(int)
    print(f"Accuracy (group holdout, threshold={BEST_THRESHOLD}): ", end="")
    print(accuracy_score(labels.iloc[test_indices], predictions))
    print(classification_report(labels.iloc[test_indices], predictions, zero_division=0))
    print(confusion_matrix(labels.iloc[test_indices], predictions))

    pipeline.fit(texts, labels)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)

    metadata = {
        "label_meaning": {"0": "정상(ham)", "1": "스팸(spam)"},
        "model": "TF-IDF(char_wb 2-6gram + word 1-2gram) + MultinomialNB",
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "train_data": str(DATA_PATH.relative_to(PROJECT_ROOT)),
        "train_rows": int(len(texts)),
        "default_threshold": BEST_THRESHOLD,
        "split_strategy": "normalized-template GroupShuffleSplit",
    }
    META_PATH.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"모델 저장 완료: {MODEL_PATH}")
    print(f"메타 정보 저장 완료: {META_PATH}")


if __name__ == "__main__":
    train_and_export()
