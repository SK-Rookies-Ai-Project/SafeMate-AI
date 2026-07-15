"""url_binary_dataset.csv 전체(17.4M행)로 URL 위험도 모델 본 학습.

흐름:
1. raw URL 전량 로딩 → 병렬 feature 추출 (src/analyzers/url/features.py)
2. 층화 5% holdout 분리
3. 20만 건 서브샘플로 RandomizedSearchCV 하이퍼파라미터 튜닝
4. 최적 파라미터로 본 학습
   - xgboost: 학습 데이터 전체
   - randomforest: 2M 층화 샘플 (트리 메모리 한계)
5. holdout 평가 후 models/ 에 저장, 최고 성능 모델을 기본 경로로 복사

실행:
    .venv/bin/python scripts/train_url_model.py
    .venv/bin/python scripts/train_url_model.py --per-class 100000  # 빠른 시험
"""

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import RandomizedSearchCV, train_test_split
from sklearn.preprocessing import LabelEncoder

from src.analyzers.url import features
from src.analyzers.url.constants import MODELS_DIR, URL_BINARY_CSV
from src.analyzers.url.schemas import ModelBundle
from src.analyzers.url.training import DEFAULT_PARAM_DISTRIBUTIONS, create_model

RANDOM_STATE = 42
TEST_SIZE = 0.05
TUNE_SAMPLE = 200_000
RF_FIT_CAP = 2_000_000
CHUNK = 100_000


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _extract_chunk(urls: list) -> pd.DataFrame:
    df = features.clean_feature_matrix(features.build_url_dataset(urls))
    return df.astype(np.float32)


def extract_parallel(urls: list, workers: int) -> pd.DataFrame:
    chunks = [urls[i:i + CHUNK] for i in range(0, len(urls), CHUNK)]
    parts = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, part in enumerate(pool.map(_extract_chunk, chunks)):
            parts.append(part)
            if (i + 1) % 20 == 0:
                log(f"  feature 추출 {min((i + 1) * CHUNK, len(urls)):,}/{len(urls):,}")
    return pd.concat(parts, ignore_index=True)


def stratified_take(x, y, n, seed=RANDOM_STATE):
    """최대 n개 층화 샘플의 (x, y)를 반환."""
    if len(y) <= n:
        return x, y
    idx, _ = train_test_split(
        np.arange(len(y)), train_size=n, random_state=seed, stratify=y
    )
    return x.iloc[idx], y[idx]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-class", type=int, default=0,
                        help="클래스당 최대 행 수 (0=전체)")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--n-iter", type=int, default=12,
                        help="RandomizedSearchCV 반복 수")
    parser.add_argument("--gpu", action="store_true",
                        help="xgboost를 CUDA로 학습 (randomforest는 CPU 전용)")
    parser.add_argument("--tag", default="",
                        help="모델 파일명 접미사. 시험 실행 시 지정해 "
                             "기본 모델을 덮어쓰지 않도록 한다")
    args = parser.parse_args()
    tag = f"_{args.tag}" if args.tag else ""

    log(f"CSV 로딩: {URL_BINARY_CSV}")
    raw = pd.read_csv(URL_BINARY_CSV, encoding="utf-8-sig")
    log(f"로딩 완료: {len(raw):,}행 {raw['status'].value_counts().to_dict()}")

    if args.per_class:
        raw = raw.groupby("status").sample(
            n=args.per_class, random_state=RANDOM_STATE
        )
        log(f"클래스당 {args.per_class:,}행 샘플링 → {len(raw):,}행")

    urls = raw["url"].astype(str).str.strip().str.strip("'\"").tolist()
    labels = raw["status"].to_numpy()
    del raw

    log(f"feature 추출 시작 (workers={args.workers})")
    t0 = time.time()
    x_all = extract_parallel(urls, args.workers)
    del urls
    log(f"feature 추출 완료: {x_all.shape}, {time.time() - t0:.0f}s")

    encoder = LabelEncoder()
    y_all = encoder.fit_transform(labels)

    x_train, x_test, y_train, y_test = train_test_split(
        x_all, y_all, test_size=TEST_SIZE,
        random_state=RANDOM_STATE, stratify=y_all,
    )
    del x_all, y_all
    log(f"train {len(y_train):,} / test {len(y_test):,}")

    x_tune, y_tune = stratified_take(x_train, y_train, TUNE_SAMPLE)
    results = {}

    for model_type in ("xgboost", "randomforest"):
        # sklearn RF는 GPU 미지원 — xgboost만 CUDA 사용
        gpu_params = (
            {"device": "cuda"} if args.gpu and model_type == "xgboost" else {}
        )
        log(f"=== {model_type} 튜닝 시작 (n={len(y_tune):,}, n_iter={args.n_iter}, "
            f"{'GPU' if gpu_params else 'CPU'}) ===")
        t0 = time.time()
        search = RandomizedSearchCV(
            create_model(model_type, RANDOM_STATE, n_jobs=4, **gpu_params),
            DEFAULT_PARAM_DISTRIBUTIONS[model_type],
            n_iter=args.n_iter,
            cv=3,
            scoring="f1_macro",
            random_state=RANDOM_STATE,
            n_jobs=2 if gpu_params else 8,  # GPU 하나에 과한 동시 fit 방지
        )
        search.fit(x_tune, y_tune)
        best_params = search.best_params_
        log(f"{model_type} 튜닝 완료 {time.time() - t0:.0f}s, "
            f"cv f1_macro={search.best_score_:.4f}, params={best_params}")

        if model_type == "randomforest":
            x_fit, y_fit = stratified_take(x_train, y_train, RF_FIT_CAP)
        else:
            x_fit, y_fit = x_train, y_train
        log(f"{model_type} 본 학습 시작 (n={len(y_fit):,})")
        t0 = time.time()
        model = create_model(model_type, RANDOM_STATE, **gpu_params, **best_params)
        model.fit(x_fit, y_fit)
        fit_seconds = time.time() - t0
        log(f"{model_type} 본 학습 완료 {fit_seconds:.0f}s")
        if gpu_params:
            # 추론은 보통 CPU에서 하므로 장치 불일치 경고/오버헤드 방지
            model.set_params(device="cpu")

        pred = model.predict(x_test)
        proba = model.predict_proba(x_test)[:, 1]
        metrics = {
            "accuracy": float(accuracy_score(y_test, pred)),
            "f1_macro": float(f1_score(y_test, pred, average="macro")),
            "roc_auc": float(roc_auc_score(y_test, proba)),
            "cv_f1_macro": float(search.best_score_),
            "n_train": int(len(y_fit)),
            "n_test": int(len(y_test)),
            "fit_seconds": round(fit_seconds, 1),
        }
        log(f"{model_type} holdout: {metrics}")

        bundle = ModelBundle(
            model=model,
            kind="feature",
            model_type=model_type,
            feature_names=list(x_train.columns),
            label_encoder=encoder,
            params=best_params,
            metrics=metrics,
            name=f"url-binary-full-{model_type}",
        )
        path = bundle.save(MODELS_DIR / f"url_feature_{model_type}{tag}.joblib")
        log(f"저장: {path}")
        results[model_type] = (bundle, metrics)

    best_type = max(results, key=lambda k: results[k][1]["f1_macro"])
    best_bundle = results[best_type][0]
    default_path = best_bundle.save(MODELS_DIR / f"url_feature_model{tag}.joblib")
    log(f"최고 성능 모델({best_type}) → 기본 경로 저장: {default_path}")

    sanity = [
        "https://www.google.com/search?q=hello",
        "https://www.naver.com/",
        "http://211.239.150.212/secure-login/verify.php?acc=x1y2&token=aaaabbbb",
        "www.anita-gd.com/images/?ref=http://%2fus.battle.net/%2fd3/%2fen/%2findex",
    ]
    for model_type, (bundle, _) in results.items():
        preds = bundle.predict_labels(sanity)
        log(f"[{model_type}] sanity: "
            + json.dumps(dict(zip(sanity, preds.tolist())), ensure_ascii=False))

    log("완료")
    print(json.dumps(
        {k: m for k, (_, m) in results.items()}, ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
