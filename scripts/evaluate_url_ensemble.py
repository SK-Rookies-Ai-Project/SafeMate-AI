"""저장된 URL 모델의 가중 확률 앙상블을 같은 holdout에서 평가한다.

기본값은 train_url_model.py의 600만 행 표본, 5% holdout, random_state=42와
같아 url_char_charlstm.joblib과 url_feature_xgboost.joblib을 바로 비교한다.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analyzers.url.constants import MODELS_DIR, URL_BINARY_CSV
from src.analyzers.url.schemas import ModelBundle


log = logging.getLogger("evaluate_url_ensemble")


def _aligned_probabilities(bundle: ModelBundle, urls, classes: list[str]) -> np.ndarray:
    proba = bundle.predict_proba(urls)
    if proba is None:
        raise ValueError(f"{bundle.name} 모델이 확률 예측을 지원하지 않습니다.")
    missing = set(classes) - set(proba.columns)
    if missing:
        raise ValueError(f"{bundle.name}에 없는 클래스: {sorted(missing)}")
    return proba.reindex(columns=classes).to_numpy(dtype=np.float64)


def _metrics(y_true, probabilities: np.ndarray, classes: list[str]) -> dict:
    predicted = np.asarray(classes)[probabilities.argmax(axis=1)]
    result = {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "f1_macro": float(f1_score(y_true, predicted, average="macro")),
    }
    risk_indices = [
        i for i, label in enumerate(classes)
        if label.lower() not in {"benign", "정상"}
    ]
    if len(risk_indices) == 1:
        risk_idx = risk_indices[0]
        result["roc_auc"] = float(
            roc_auc_score(np.asarray(y_true) == classes[risk_idx], probabilities[:, risk_idx])
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=URL_BINARY_CSV, type=Path)
    parser.add_argument("--char-model", default=MODELS_DIR / "url_char_charlstm.joblib",
                        type=Path)
    parser.add_argument("--feature-model", default=MODELS_DIR / "url_feature_xgboost.joblib",
                        type=Path)
    parser.add_argument("--nrows", type=int, default=6_000_000)
    parser.add_argument("--test-size", type=float, default=0.05)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--weight-step", type=float, default=0.05,
                        help="char 모델 가중치 탐색 간격")
    parser.add_argument("--output", default=MODELS_DIR / "url_ensemble_metrics.json",
                        type=Path)
    args = parser.parse_args()
    if not 0 < args.weight_step <= 1:
        parser.error("--weight-step은 0 초과 1 이하여야 합니다.")

    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s",
                        datefmt="%H:%M:%S")
    char_bundle = ModelBundle.load(args.char_model)
    feature_bundle = ModelBundle.load(args.feature_model)

    log.info("CSV 로딩: %s", args.csv)
    df = pd.read_csv(args.csv)
    if args.nrows:
        df = df.sample(n=args.nrows, random_state=args.random_state)
    urls = df.iloc[:, 0].astype(str).tolist()
    labels = df.iloc[:, 1].astype(str).tolist()
    _, urls_test, _, y_test = train_test_split(
        urls,
        labels,
        test_size=args.test_size,
        random_state=args.random_state,
        stratify=labels,
    )
    del df, urls, labels

    classes = sorted(set(char_bundle.label_encoder.classes_))
    if classes != sorted(set(feature_bundle.label_encoder.classes_)):
        raise ValueError("두 모델의 라벨 클래스가 일치하지 않습니다.")
    log.info("holdout 확률 예측: n=%s", f"{len(urls_test):,}")
    char_proba = _aligned_probabilities(char_bundle, urls_test, classes)
    feature_proba = _aligned_probabilities(feature_bundle, urls_test, classes)

    weights = np.arange(0, 1 + args.weight_step / 2, args.weight_step)
    rows = []
    for char_weight in weights:
        probabilities = (
            char_weight * char_proba + (1.0 - char_weight) * feature_proba
        )
        metrics = _metrics(y_test, probabilities, classes)
        rows.append({"char_weight": round(float(char_weight), 4), **metrics})
        log.info("char_weight=%.2f %s", char_weight, metrics)

    best = max(rows, key=lambda row: row["f1_macro"])
    result = {
        "char_model": str(args.char_model),
        "feature_model": str(args.feature_model),
        "n_test": len(urls_test),
        "classes": classes,
        "best": best,
        "all_weights": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("최고 앙상블: %s", best)
    log.info("저장: %s", args.output)


if __name__ == "__main__":
    main()
