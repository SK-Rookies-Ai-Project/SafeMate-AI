"""url_binary_dataset.csv(17.4M행)를 TF-IDF(유형2) 방식으로 URL 모델 학습.

흐름: CSV 로딩 → stratified split → train 표본으로 vectorizer fit(누수 방지)
      → 병렬 TF-IDF transform → (모델별) 서브샘플 튜닝 → 학습
      → holdout 평가 → ModelBundle(kind='tfidf') 저장.

메모리 주의: char 3~5-gram TF-IDF는 희소행렬이라도 전체 17.4M행이면
수십 GB가 될 수 있다. 시험은 --nrows로, 상시 학습은 --max-features로 조절.

사용 예:
    # 전체 데이터, 기본 3개 모델 (randomforest/xgboost/logistic)
    .venv/bin/python scripts/train_url_model_tfidf.py

    # 빠른 시험 (랜덤 20만 행, 튜닝 생략)
    .venv/bin/python scripts/train_url_model_tfidf.py --nrows 200000 --no-tune

    # LSTM은 희소행렬을 dense로 풀어 seq_len=max_features가 되므로
    # 반드시 작은 vocab으로만 (예: 행 10만 × feature 2천)
    .venv/bin/python scripts/train_url_model_tfidf.py \
        --models lstm --nrows 100000 --max-features 2000 --no-tune
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
from scipy import sparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.preprocessing import LabelEncoder

from src.analyzers.url import prediction, training
from src.analyzers.url.constants import MODELS_DIR, URL_BINARY_CSV
from src.analyzers.url.datasets import dedup_group_split
from src.analyzers.url.features import build_tfidf_vectorizer, clean_url
from src.analyzers.url.model_registry import MODEL_FACTORIES, create_model
from src.analyzers.url.schemas import DataSet, ModelBundle

log = logging.getLogger("train_url_model_tfidf")

DEFAULT_MODEL_PATH = MODELS_DIR / "url_tfidf_model.joblib"

# lstm은 sparse → dense 변환(n행 × max_features)이 필요해 기본에서 제외
DEFAULT_MODELS = ["logistic", "randomforest", "xgboost"]

# 전체(16.5M행) 학습이 비현실적으로 느린 모델은 학습 표본을 상한으로 자른다
MAX_FIT_ROWS = {
    "randomforest": 2_000_000,
    "lstm": 100_000,  # dense 변환 + seq_len=vocab 크기라 극히 무겁다
    "logistic": 4_000_000,
}

SANITY_URLS = [
    "https://www.google.com/search?q=hello",
    "https://www.naver.com/",
    "http://211.239.150.212/secure-login/verify.php?acc=x1y2&token=aaaabbbb",
    "www.anita-gd.com/images/?ref=http://%2fus.battle.net/%2fd3/%2fen/%2findex",
]


# ---------------------------------------------------------------------------
# TF-IDF 데이터셋 생성 (fit은 train 표본, transform은 멀티프로세스)
# ---------------------------------------------------------------------------

_VECTORIZER = None  # transform 워커 프로세스에 1회만 전달하기 위한 전역


def _init_transform_worker(vectorizer):
    global _VECTORIZER
    _VECTORIZER = vectorizer


def _transform_chunk(urls) -> sparse.csr_matrix:
    return _VECTORIZER.transform([clean_url(u) for u in urls])


def fit_vectorizer(urls, args):
    """train URL(필요 시 랜덤 표본)로 TF-IDF vectorizer를 fit."""
    n = len(urls)
    if args.vectorizer_sample and n > args.vectorizer_sample:
        idx = np.random.default_rng(args.random_state).choice(
            n, size=args.vectorizer_sample, replace=False
        )
        sample = [urls[i] for i in idx]
    else:
        sample = urls
    vectorizer = build_tfidf_vectorizer(
        ngram_range=(args.ngram_min, args.ngram_max),
        min_df=args.min_df,
        max_features=args.max_features,
        dtype=np.float32,  # nnz 수십억 스케일에서 float64 대비 메모리 절반
    )
    log.info("vectorizer fit 시작 (n=%s)", f"{len(sample):,}")
    started = time.time()
    vectorizer.fit(clean_url(u) for u in sample)
    log.info("vectorizer fit 완료: vocab=%s, %.0fs",
             f"{len(vectorizer.vocabulary_):,}", time.time() - started)
    return vectorizer


def transform_parallel(vectorizer, urls, workers: int,
                       chunk_rows: int = 200_000) -> sparse.csr_matrix:
    started = time.time()
    chunks = [urls[i:i + chunk_rows] for i in range(0, len(urls), chunk_rows)]
    log.info("TF-IDF transform 시작 (workers=%d)", workers)
    parts, done = [], 0
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_transform_worker,
        initargs=(vectorizer,),
    ) as ex:
        for part in ex.map(_transform_chunk, chunks):
            parts.append(part)
            done += part.shape[0]
            if done % 2_000_000 < chunk_rows and done < len(urls):
                log.info("  transform %s/%s", f"{done:,}", f"{len(urls):,}")
    x = sparse.vstack(parts, format="csr")
    log.info("TF-IDF transform 완료: %s (nnz=%s), %.0fs",
             x.shape, f"{x.nnz:,}", time.time() - started)
    return x


# ---------------------------------------------------------------------------
# 모델 1개 학습
# ---------------------------------------------------------------------------

def train_one(model_type, x_train, y_train, x_test, y_test,
              encoder, vectorizer, args):
    random_state = args.random_state

    if model_type == "lstm" and x_train.shape[1] > 5_000:
        log.warning(
            "lstm은 dense 변환(행수 × %d) 때문에 메모리가 폭증할 수 있습니다 — "
            "--max-features를 수천 이하로 낮추길 권장", x_train.shape[1]
        )

    model = create_model(model_type, random_state)
    best_params = {}

    # 튜닝은 서브샘플로 (전체 데이터 RandomizedSearchCV는 비현실적)
    tune = args.tune and (model_type != "lstm" or args.tune_lstm)
    if tune:
        n = min(args.tune_sample, x_train.shape[0])
        idx = np.random.default_rng(random_state).choice(
            x_train.shape[0], size=n, replace=False
        )
        sub = DataSet(x_train[idx], y_train[idx],
                      name="tfidf-tune-sub", random_state=random_state)
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
    if cap and x_train.shape[0] > cap:
        idx = np.random.default_rng(random_state).choice(
            x_train.shape[0], size=cap, replace=False
        )
        fit_x, fit_y = x_train[idx], y_train[idx]
    else:
        fit_x, fit_y = x_train, y_train

    log.info("%s 본 학습 시작 (n=%s)", model_type, f"{fit_x.shape[0]:,}")
    started = time.time()
    model.fit(fit_x, fit_y)
    fit_seconds = time.time() - started
    log.info("%s 본 학습 완료 %.0fs", model_type, fit_seconds)

    # holdout 평가
    pred = model.predict(x_test)
    metrics = {
        "accuracy": float(accuracy_score(y_test, pred)),
        "f1_macro": float(f1_score(y_test, pred, average="macro")),
        "n_train": int(fit_x.shape[0]),
        "n_test": int(x_test.shape[0]),
        "fit_seconds": round(fit_seconds, 1),
    }
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x_test)
        risk_idx = list(encoder.classes_).index("악성")
        metrics["roc_auc"] = float(
            roc_auc_score(y_test == risk_idx, proba[:, risk_idx])
        )
    log.info("%s holdout: %s", model_type, metrics)

    bundle = ModelBundle(
        model=model,
        kind="tfidf",
        model_type=model_type,
        vectorizer=vectorizer,
        label_encoder=encoder,
        params=best_params,
        metrics=metrics,
        name=f"url-binary-tfidf-{model_type}",
    )
    path = bundle.save(MODELS_DIR / f"url_tfidf_{model_type}.joblib")
    log.info("저장: %s", path)
    return bundle


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=URL_BINARY_CSV, type=Path)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                        choices=sorted(MODEL_FACTORIES))
    parser.add_argument("--nrows", type=int, default=None,
                        help="전체 대신 랜덤 표본 n행만 사용 (시험용)")
    parser.add_argument("--test-size", type=float, default=0.05)
    parser.add_argument("--split", default="group",
                        choices=["group", "random"],
                        help="group: 등록 도메인(eTLD+1) 단위 분리로 "
                             "train/test 도메인 누수 차단 (기본), "
                             "random: 기존 URL 단위 랜덤 분리")
    parser.add_argument("--dedup", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="canonical 중복·라벨충돌 행 제거 (기본: 켜짐)")
    parser.add_argument("--tune", action=argparse.BooleanOptionalAction,
                        default=True)
    parser.add_argument("--tune-lstm", action="store_true",
                        help="LSTM도 튜닝 (CPU에서는 매우 느림)")
    parser.add_argument("--tune-sample", type=int, default=200_000)
    parser.add_argument("--tune-iter", type=int, default=12)
    parser.add_argument("--max-fit-rows", type=int, default=None,
                        help="모든 모델의 학습 표본 상한 (기본: 모델별 기본값)")
    parser.add_argument("--vectorizer-sample", type=int, default=2_000_000,
                        help="vectorizer fit에 쓸 train 표본 상한 "
                             "(0이면 train 전체로 fit — 매우 느림)")
    parser.add_argument("--max-features", type=int, default=100_000)
    parser.add_argument("--ngram-min", type=int, default=3)
    parser.add_argument("--ngram-max", type=int, default=5)
    parser.add_argument("--min-df", type=int, default=2)
    parser.add_argument("--workers", type=int, default=os.cpu_count())
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
    log.info("========== 새 TF-IDF 학습 실행: models=%s nrows=%s tune=%s "
             "max_features=%s ==========",
             args.models, args.nrows, args.tune, args.max_features)

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

    # 2) 라벨 인코딩 + dedup + split (기본: 등록 도메인 group split)
    #    (vectorizer를 train으로만 fit해 test 누수를 막기 위해 split을 먼저)
    encoder = LabelEncoder()
    y = encoder.fit_transform(labels)
    urls_train, urls_test, y_train, y_test = dedup_group_split(
        urls, y, test_size=args.test_size, random_state=args.random_state,
        dedup=args.dedup, split=args.split,
    )
    del urls, labels
    log.info("train %s / test %s (split=%s, dedup=%s)",
             f"{len(urls_train):,}", f"{len(urls_test):,}",
             args.split, args.dedup)

    # 3) TF-IDF 데이터셋 생성
    vectorizer = fit_vectorizer(urls_train, args)
    x_train = transform_parallel(vectorizer, urls_train, workers=args.workers)
    x_test = transform_parallel(vectorizer, urls_test, workers=args.workers)
    del urls_train, urls_test

    # 4) 모델별 학습
    bundles = {}
    for model_type in args.models:
        bundles[model_type] = train_one(
            model_type, x_train, y_train, x_test, y_test,
            encoder, vectorizer, args,
        )

    # 5) 최고 성능(f1_macro) 모델을 기본 경로로 저장
    #    (일부 모델만 돌린 실행이 더 좋은 기존 번들을 덮어쓰지 않도록 비교)
    best_type = max(bundles, key=lambda k: bundles[k].metrics["f1_macro"])
    best_f1 = bundles[best_type].metrics["f1_macro"]
    current_f1 = -1.0
    if DEFAULT_MODEL_PATH.exists():
        try:
            current_f1 = ModelBundle.load(DEFAULT_MODEL_PATH).metrics.get(
                "f1_macro", -1.0
            )
        except Exception:
            pass
    if best_f1 >= current_f1:
        bundles[best_type].save(DEFAULT_MODEL_PATH)
        log.info("최고 성능 모델(%s) → 기본 경로 저장: %s",
                 best_type, DEFAULT_MODEL_PATH)
    else:
        log.info("기본 경로 유지: 기존 번들 f1=%.4f > 이번 최고 %s f1=%.4f",
                 current_f1, best_type, best_f1)

    # 6) sanity check
    for model_type, bundle in bundles.items():
        verdicts = prediction.analyze_urls(bundle, SANITY_URLS)
        log.info("[%s] sanity: %s",
                 model_type, json.dumps(verdicts, ensure_ascii=False))
    log.info("완료")


if __name__ == "__main__":
    main()
