"""URL 위험도 분석 메인 진입 파일.

세부 구현은 src/analyzers/url/ 서브패키지에 있고, 여기서는 외부(파이프라인,
UI)가 쓰는 진입 API만 노출한다.

사용 예:
    from src.analyzers.url_analyzer import analyze_urls, train_default_model

    bundle = train_default_model()            # 또는 ModelBundle.load(path)
    result = analyze_urls(urls, bundle=bundle)
    # → {"http://...": "위험", "https://...": "안전", ...}
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence, Union

from src.analyzers.url import prediction, training
from src.analyzers.url.constants import MODELS_DIR
from src.analyzers.url.schemas import DataSet, ModelBundle

# 기존 import 호환용 재노출
from src.analyzers.url import (  # noqa: F401
    FEATURE_NAMES,
    build_url_dataset,
    extract_url_features,
)

DEFAULT_MODEL_PATH = MODELS_DIR / "url_feature_model.joblib"
DEFAULT_TFIDF_MODEL_PATH = MODELS_DIR / "url_tfidf_model.joblib"
DEFAULT_MODEL_PATHS = {
    "feature": DEFAULT_MODEL_PATH,
    "tfidf": DEFAULT_TFIDF_MODEL_PATH,
}


def resolve_model_path(
    model_path: Optional[Union[str, Path]] = None,
    model_kind: str = "feature",
) -> Path:
    """Return an explicit model path or the default path for a model kind."""
    if model_path is not None:
        return Path(model_path)
    try:
        return DEFAULT_MODEL_PATHS[model_kind]
    except KeyError as exc:
        raise ValueError(f"unsupported url model kind: {model_kind!r}") from exc


def load_model(path: Union[str, Path] = DEFAULT_MODEL_PATH) -> ModelBundle:
    """저장된 모델 번들 로딩."""
    return ModelBundle.load(path)


@lru_cache(maxsize=4)
def _load_model_cached(path: str) -> ModelBundle:
    return load_model(path)


def get_default_model(
    model_path: Union[str, Path] = DEFAULT_MODEL_PATH,
) -> ModelBundle:
    """Return the cached default URL model bundle."""
    return _load_model_cached(str(Path(model_path)))


def train_default_model(
    model_type: str = "randomforest",
    tune: bool = False,
    save_path: Optional[Union[str, Path]] = DEFAULT_MODEL_PATH,
    nrows: Optional[int] = None,
) -> ModelBundle:
    """All.csv로 기본 feature 모델을 학습하고 저장."""
    dataset = training.load_feature_csv(nrows=nrows)
    bundle = training.train_model(dataset, model_type=model_type, tune=tune)
    if save_path:
        bundle.save(save_path)
        _load_model_cached.cache_clear()
    return bundle


def train_default_tfidf_model(
    model_type: str = "logistic",
    tune: bool = False,
    save_path: Optional[Union[str, Path]] = DEFAULT_TFIDF_MODEL_PATH,
    nrows: Optional[int] = None,
    **vectorizer_params,
) -> ModelBundle:
    """Train a default TF-IDF URL model from raw URLs and optionally save it."""
    urls, labels = training.load_url_csv(nrows=nrows)
    dataset, vectorizer = training.make_tfidf_dataset(
        urls,
        labels=labels,
        **vectorizer_params,
    )
    bundle = training.train_model(
        dataset,
        model_type=model_type,
        kind="tfidf",
        vectorizer=vectorizer,
        tune=tune,
    )
    if save_path:
        bundle.save(save_path)
        _load_model_cached.cache_clear()
    return bundle


def analyze_url(
    url: str,
    bundle: Optional[ModelBundle] = None,
    model_path: Optional[Union[str, Path]] = None,
    model_kind: str = "feature",
) -> dict:
    """Analyze one URL and return the SafeMate URL model contract."""
    validation_error = prediction.validate_url(url)
    if validation_error:
        return {
            "status": "error",
            "url": url if isinstance(url, str) else "",
            "label": "unknown",
            "risk_score": None,
            "signals": [],
            "features": [],
            "model_version": prediction.MODEL_VERSION,
            "error": validation_error,
        }
    try:
        if bundle is None:
            bundle = get_default_model(resolve_model_path(model_path, model_kind))
        return prediction.analyze_url(bundle, url)
    except FileNotFoundError:
        return {
            "status": "error",
            "url": url if isinstance(url, str) else "",
            "label": "unknown",
            "risk_score": None,
            "signals": [],
            "features": [],
            "model_version": prediction.MODEL_VERSION,
            "error": "url model is not available",
        }
    except Exception:
        return {
            "status": "error",
            "url": url if isinstance(url, str) else "",
            "label": "unknown",
            "risk_score": None,
            "signals": [],
            "features": [],
            "model_version": prediction.MODEL_VERSION,
            "error": "url analysis failed",
        }


def analyze_urls(
    urls: Sequence[str],
    bundle: Optional[ModelBundle] = None,
    model_path: Optional[Union[str, Path]] = None,
    model_kind: str = "feature",
) -> dict:
    """URL 배열 → {링크: '위험'/'안전'} 딕셔너리 (프로그램 최종 출력 형식)."""
    if bundle is None:
        bundle = get_default_model(resolve_model_path(model_path, model_kind))
    return prediction.analyze_urls(bundle, urls)


def analyze_urls_detail(
    urls: Sequence[str],
    bundle: Optional[ModelBundle] = None,
    model_path: Optional[Union[str, Path]] = None,
    model_kind: str = "feature",
) -> list:
    """상세 결과(라벨, 위험 점수, 판단 근거 포함) — 디버그/UI용."""
    if bundle is None:
        bundle = get_default_model(resolve_model_path(model_path, model_kind))
    return prediction.predict_urls(bundle, urls)
