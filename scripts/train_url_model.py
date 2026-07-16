"""url_binary_dataset.csv(17.4M행) 전체를 대상으로 URL 모델 학습.

흐름: CSV 로딩 → 병렬 lexical feature 추출 → stratified split
      → (모델별) 서브샘플 튜닝 → 학습 → holdout 평가 → ModelBundle 저장.

사용 예:
    # 전체 데이터, 4개 모델 전부
    .venv/bin/python scripts/train_url_model.py

    # 빠른 시험 (랜덤 20만 행, 튜닝 생략)
    .venv/bin/python scripts/train_url_model.py --nrows 200000 --no-tune

    # 특정 모델만
    .venv/bin/python scripts/train_url_model.py --models lstm logistic
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

from src.analyzers.url import prediction, training
from src.analyzers.url.constants import MODELS_DIR, URL_BINARY_CSV
from src.analyzers.url.features import (
    FEATURE_NAMES,
    canonicalize_url_for_tfidf,
    extract_url_features,
)
from src.analyzers.url.model_registry import MODEL_FACTORIES, create_model
from src.analyzers.url.schemas import DataSet, ModelBundle

log = logging.getLogger("train_url_model")

DEFAULT_MODEL_PATH = MODELS_DIR / "url_feature_model.joblib"
DEFAULT_MODEL_PATHS = {
    "feature": MODELS_DIR / "url_feature_model.joblib",
    "tfidf": MODELS_DIR / "url_tfidf_model.joblib",
}

# 전체(16.5M행) 학습이 비현실적으로 느린 모델은 학습 표본을 상한으로 자른다
MAX_FIT_ROWS = {
    "randomforest": 2_000_000,
    "lstm": 2_000_000,
    "logistic": 4_000_000,  # lbfgs는 이 이상에서 시간 대비 이득이 없음
}

# LSTM은 17M 스케일에 맞게 기본값보다 큰 배치/짧은 epoch 사용
LSTM_PARAMS = dict(hidden_size=64, epochs=5, batch_size=1024, lr=1e-3)

SANITY_URLS = [
    "https://www.google.com/search?q=hello",
    "https://www.naver.com/",
    "http://211.239.150.212/secure-login/verify.php?acc=x1y2&token=aaaabbbb",
    "www.anita-gd.com/images/?ref=http://%2fus.battle.net/%2fd3/%2fen/%2findex",
]


# ---------------------------------------------------------------------------
# feature 추출 (멀티프로세스)
# ---------------------------------------------------------------------------

def _extract_chunk(urls) -> np.ndarray:
    rows = [extract_url_features(u) for u in urls]
    return np.asarray(
        [[row[name] for name in FEATURE_NAMES] for row in rows],
        dtype=np.float32,
    )


def extract_features_parallel(urls, workers: int, chunk_rows: int = 100_000):
    started = time.time()
    chunks = [urls[i:i + chunk_rows] for i in range(0, len(urls), chunk_rows)]
    log.info("feature 추출 시작 (workers=%d)", workers)
    # vstack은 피크 메모리가 2배라 미리 할당한 배열에 순서대로 채운다
    x = np.empty((len(urls), len(FEATURE_NAMES)), dtype=np.float32)
    offset = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for part in ex.map(_extract_chunk, chunks):
            x[offset:offset + len(part)] = part
            offset += len(part)
            if offset % 2_000_000 < chunk_rows and offset < len(urls):
                log.info("  feature 추출 %s/%s",
                         f"{offset:,}", f"{len(urls):,}")
    # clean_feature_matrix와 동일 규칙: ±inf/NaN → -1
    np.nan_to_num(x, copy=False, nan=-1.0, posinf=-1.0, neginf=-1.0)
    log.info("feature 추출 완료: %s, %.0fs", x.shape, time.time() - started)
    return pd.DataFrame(x, columns=FEATURE_NAMES)


def build_tfidf_matrices(urls_train, urls_test, args):
    started = time.time()
    vectorizer = training.build_tfidf_vectorizer(
        analyzer=args.tfidf_analyzer,
        ngram_range=tuple(args.tfidf_ngram_range),
        min_df=args.tfidf_min_df,
        max_features=args.tfidf_max_features,
        lowercase=True,
    )
    log.info("tfidf fit_transform 시작 (n=%s)", f"{len(urls_train):,}")
    x_train = vectorizer.fit_transform([
        canonicalize_url_for_tfidf(u) for u in urls_train
    ])
    x_test = vectorizer.transform([
        canonicalize_url_for_tfidf(u) for u in urls_test
    ])
    log.info(
        "tfidf 완료: train=%s test=%s, %.0fs",
        x_train.shape,
        x_test.shape,
        time.time() - started,
    )
    if args.tfidf_svd_dims:
        x_train, x_test, vectorizer = training.reduce_tfidf_dimensions(
            x_train,
            x_test,
            vectorizer,
            n_components=args.tfidf_svd_dims,
            random_state=args.random_state,
        )
    return x_train, x_test, vectorizer


def _row_subset(x, idx):
    return x.iloc[idx] if hasattr(x, "iloc") else x[idx]


def _n_rows(x):
    return x.shape[0]


# ---------------------------------------------------------------------------
# 모델 1개 학습
# ---------------------------------------------------------------------------

def train_one(
    model_type,
    x_train,
    y_train,
    x_test,
    y_test,
    encoder,
    args,
    kind="feature",
    vectorizer=None,
):
    random_state = args.random_state
    params = dict(LSTM_PARAMS) if model_type == "lstm" else {}

    model = create_model(model_type, random_state, **params)
    best_params = dict(params)

    # 튜닝은 서브샘플로 (전체 데이터 RandomizedSearchCV는 비현실적)
    tune = args.tune and (model_type != "lstm" or args.tune_lstm)
    if tune:
        n = min(args.tune_sample, _n_rows(x_train))
        idx = np.random.default_rng(random_state).choice(
            _n_rows(x_train), size=n, replace=False
        )
        sub = DataSet(_row_subset(x_train, idx), y_train[idx],
                      name="tune-sub", random_state=random_state)
        log.info("=== %s 튜닝 시작 (n=%s, n_iter=%d) ===",
                 model_type, f"{n:,}", args.tune_iter)
        started = time.time()
        model, tuned = training.tune_hyperparameters(
            model, sub, model_type=model_type, n_iter=args.tune_iter
        )
        best_params.update(tuned)
        log.info("%s 튜닝 완료 %.0fs, params=%s",
                 model_type, time.time() - started, tuned)

    # 본 학습 (모델별 상한 적용)
    cap = args.max_fit_rows or MAX_FIT_ROWS.get(model_type)
    if cap and _n_rows(x_train) > cap:
        idx = np.random.default_rng(random_state).choice(
            _n_rows(x_train), size=cap, replace=False
        )
        fit_x, fit_y = _row_subset(x_train, idx), y_train[idx]
    else:
        fit_x, fit_y = x_train, y_train

    log.info("%s 본 학습 시작 (n=%s)", model_type, f"{_n_rows(fit_x):,}")
    started = time.time()
    model.fit(fit_x, fit_y)
    fit_seconds = time.time() - started
    log.info("%s 본 학습 완료 %.0fs", model_type, fit_seconds)

    # holdout 평가
    pred = model.predict(x_test)
    metrics = {
        "accuracy": float(accuracy_score(y_test, pred)),
        "f1_macro": float(f1_score(y_test, pred, average="macro")),
        "n_train": _n_rows(fit_x),
        "n_test": _n_rows(x_test),
        "fit_seconds": round(fit_seconds, 1),
    }
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x_test)
        classes = [str(label).lower() for label in encoder.classes_]
        risk_indices = [
            i for i, label in enumerate(classes)
            if label not in {"benign", "정상"}
        ]
        if len(risk_indices) == 1:
            risk_idx = risk_indices[0]
            metrics["roc_auc"] = float(
                roc_auc_score(y_test == risk_idx, proba[:, risk_idx])
            )
    log.info("%s holdout: %s", model_type, metrics)

    bundle = ModelBundle(
        model=model,
        kind=kind,
        model_type=model_type,
        vectorizer=vectorizer,
        feature_names=list(FEATURE_NAMES) if kind == "feature" else None,
        label_encoder=encoder,
        params=best_params,
        metrics=metrics,
        name=f"url-binary-{kind}-{model_type}",
    )
    path = bundle.save(MODELS_DIR / f"url_{kind}_{model_type}.joblib")
    log.info("저장: %s", path)
    return bundle


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=URL_BINARY_CSV, type=Path)
    parser.add_argument("--models", nargs="+", default=sorted(MODEL_FACTORIES),
                        choices=sorted(MODEL_FACTORIES))
    parser.add_argument("--representations", nargs="+", default=["feature"],
                        choices=["feature", "tfidf"],
                        help="Train lexical feature models, TF-IDF models, or both.")
    parser.add_argument("--nrows", type=int, default=None,
                        help="전체 대신 랜덤 표본 n행만 사용 (시험용)")
    parser.add_argument("--test-size", type=float, default=0.05)
    parser.add_argument("--tune", action=argparse.BooleanOptionalAction,
                        default=True)
    parser.add_argument("--tune-lstm", action="store_true",
                        help="LSTM도 튜닝 (CPU에서는 매우 느림)")
    parser.add_argument("--tune-sample", type=int, default=200_000)
    parser.add_argument("--tune-iter", type=int, default=12)
    parser.add_argument("--max-fit-rows", type=int, default=None,
                        help="모든 모델의 학습 표본 상한 (기본: 모델별 기본값)")
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument("--tfidf-analyzer", default="char_wb",
                        choices=["char", "char_wb", "word"])
    parser.add_argument("--tfidf-ngram-range", nargs=2, type=int,
                        default=[3, 5], metavar=("MIN_N", "MAX_N"))
    parser.add_argument("--tfidf-min-df", type=int, default=2)
    parser.add_argument("--tfidf-max-features", type=int, default=100_000)
    parser.add_argument("--tfidf-svd-dims", type=int, default=None,
                        help="TruncatedSVD로 축소할 차원 수 "
                             "(LSTM 등 밀집 입력 모델용, 기본: 축소 안 함)")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--log-file",
                        default=Path(__file__).with_suffix(".log"))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(args.log_file, mode="a", encoding="utf-8"),
        ],
    )
    log.info(
        "========== train: representations=%s models=%s nrows=%s tune=%s ==========",
        args.representations,
        args.models,
        args.nrows,
        args.tune,
    )

    # 1) 로딩 (CSV가 라벨순 정렬이라 nrows는 head가 아닌 랜덤 표본으로)
    log.info("CSV 로딩: %s", args.csv)
    df = pd.read_csv(args.csv)
    if args.nrows:
        df = df.sample(n=args.nrows, random_state=args.random_state)
    urls = df.iloc[:, 0].astype(str).tolist()
    labels = df.iloc[:, 1].tolist()
    log.info("로딩 완료: %s행 %s",
             f"{len(df):,}", dict(pd.Series(labels).value_counts()))
    del df

    # 2) 라벨 인코딩 + raw URL split. TF-IDF는 train 데이터에만 fit한다.
    encoder = LabelEncoder()
    y = encoder.fit_transform(labels)
    urls_train, urls_test, y_train, y_test = train_test_split(
        urls, y, test_size=args.test_size,
        random_state=args.random_state, stratify=y,
    )
    del urls
    log.info("train %s / test %s", f"{len(urls_train):,}", f"{len(urls_test):,}")

    # 3) representation별 전처리 + 모델 학습
    bundles = {}
    for representation in args.representations:
        if representation == "feature":
            x_train = extract_features_parallel(urls_train, workers=args.workers)
            x_test = extract_features_parallel(urls_test, workers=args.workers)
            vectorizer = None
        else:
            x_train, x_test, vectorizer = build_tfidf_matrices(
                urls_train,
                urls_test,
                args,
            )

        for model_type in args.models:
            key = f"{representation}:{model_type}"
            bundles[key] = train_one(
                model_type,
                x_train,
                y_train,
                x_test,
                y_test,
                encoder,
                args,
                kind=representation,
                vectorizer=vectorizer,
            )

        # 4) representation별 최고 성능(f1_macro) 모델을 기본 경로로 저장
        rep_bundles = {
            key: bundle for key, bundle in bundles.items()
            if key.startswith(f"{representation}:")
        }
        best_key = max(rep_bundles, key=lambda k: rep_bundles[k].metrics["f1_macro"])
        best_f1 = rep_bundles[best_key].metrics["f1_macro"]
        default_path = DEFAULT_MODEL_PATHS[representation]
        current_f1 = -1.0
        if default_path.exists():
            try:
                current_f1 = ModelBundle.load(default_path).metrics.get(
                    "f1_macro", -1.0
                )
            except Exception:
                pass
        if best_f1 >= current_f1:
            rep_bundles[best_key].save(default_path)
            log.info("best %s model(%s) saved to %s",
                     representation, best_key, default_path)
        else:
            log.info("default %s model kept: existing f1=%.4f > new %s f1=%.4f",
                     representation, current_f1, best_key, best_f1)

    # 5) sanity check
    for key, bundle in bundles.items():
        verdicts = prediction.analyze_urls(bundle, SANITY_URLS)
        log.info("[%s] sanity: %s", key, json.dumps(verdicts, ensure_ascii=False))
    log.info("완료")


if __name__ == "__main__":
    main()
