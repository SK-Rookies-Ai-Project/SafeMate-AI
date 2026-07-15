"""Public entry points for SafeMate URL analysis.

UI and pipeline code should call analyze_url(url) for a single URL. The trained
model bundle is loaded once and then reused by an in-process cache.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence, Union

from src.analyzers.url import prediction, training
from src.analyzers.url.constants import MODELS_DIR
from src.analyzers.url.schemas import DataSet, ModelBundle

# Backward-compatible re-exports used by older code/tests.
from src.analyzers.url import (  # noqa: F401
    FEATURE_NAMES,
    build_url_dataset,
    extract_url_features,
)

DEFAULT_MODEL_PATH = MODELS_DIR / "url_feature_model.joblib"


def load_model(path: Union[str, Path] = DEFAULT_MODEL_PATH) -> ModelBundle:
    """Load a saved URL ModelBundle from disk."""
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
    """Train the default feature model from All.csv and optionally save it."""
    dataset = training.load_feature_csv(nrows=nrows)
    bundle = training.train_model(dataset, model_type=model_type, tune=tune)
    if save_path:
        bundle.save(save_path)
        _load_model_cached.cache_clear()
    return bundle


def analyze_url(
    url: str,
    bundle: Optional[ModelBundle] = None,
    model_path: Union[str, Path] = DEFAULT_MODEL_PATH,
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
            bundle = get_default_model(model_path)
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
    model_path: Union[str, Path] = DEFAULT_MODEL_PATH,
) -> dict:
    """Legacy batch API: return {url: verdict}."""
    if bundle is None:
        bundle = get_default_model(model_path)
    return prediction.analyze_urls(bundle, urls)


def analyze_urls_detail(
    urls: Sequence[str],
    bundle: Optional[ModelBundle] = None,
    model_path: Union[str, Path] = DEFAULT_MODEL_PATH,
) -> list:
    """Legacy batch API: return detailed prediction rows."""
    if bundle is None:
        bundle = get_default_model(model_path)
    return prediction.predict_urls(bundle, urls)
