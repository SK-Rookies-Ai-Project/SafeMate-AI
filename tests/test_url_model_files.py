from pathlib import Path

import pytest

from src.analyzers import url_analyzer
from src.analyzers.url.schemas import ModelBundle


MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_FILES = sorted(MODELS_DIR.glob("*.joblib"))
KNOWN_UNLOADABLE_MODELS = {
    "url_feature_xgboost.joblib": "XGBoostError: input stream corrupted",
}


def _xfail_if_known_unloadable(model_path: Path):
    reason = KNOWN_UNLOADABLE_MODELS.get(model_path.name)
    if reason:
        pytest.xfail(reason)


def test_models_directory_exists():
    assert MODELS_DIR.is_dir()


@pytest.mark.parametrize("model_path", MODEL_FILES, ids=lambda p: p.name)
def test_joblib_model_files_load_as_model_bundle(model_path):
    _xfail_if_known_unloadable(model_path)

    bundle = ModelBundle.load(model_path)

    assert bundle.kind in {"feature", "tfidf"}
    assert bundle.model_type
    if bundle.kind == "feature":
        assert bundle.feature_names


@pytest.mark.parametrize("model_path", MODEL_FILES, ids=lambda p: p.name)
def test_joblib_model_files_can_analyze_url(model_path):
    _xfail_if_known_unloadable(model_path)

    result = url_analyzer.analyze_url(
        "https://example.com/login",
        model_path=model_path,
    )

    assert result["status"] == "success"
    assert result["url"] == "https://example.com/login"
    assert result["label"] in {"benign", "suspicious", "malicious", "unknown"}
    assert result["error"] is None
    assert isinstance(result["signals"], list)
    assert isinstance(result["features"], list)
    if result["risk_score"] is not None:
        assert 0.0 <= result["risk_score"] <= 1.0
