"""model_registry의 4개 알고리즘과 학습/예측 파이프라인 테스트.

CSV 없이 합성 URL 데이터셋으로 빠르게 돈다.
"""

import numpy as np
import pytest
from sklearn.base import clone

from src.analyzers.url import prediction, training
from src.analyzers.url.model_registry import (
    DEFAULT_PARAM_DISTRIBUTIONS,
    LSTMClassifier,
    MODEL_FACTORIES,
    create_model,
)
from src.analyzers.url.schemas import ModelBundle


def _synthetic_dataset(n_per_class: int = 20):
    """benign/malware 2클래스 합성 URL feature DataSet."""
    benign = [f"https://site{i}.example.com/page{i}" for i in range(n_per_class)]
    risky = [
        f"http://198.51.100.{i}/login.verify.update/x{i}.exe?id={i}"
        for i in range(n_per_class)
    ]
    labels = ["benign"] * n_per_class + ["malware"] * n_per_class
    return training.make_feature_dataset(benign + risky, labels, name="synthetic")


@pytest.fixture(scope="module")
def dataset():
    return _synthetic_dataset()


# ---------------------------------------------------------------------------
# 레지스트리
# ---------------------------------------------------------------------------

def test_registry_keys():
    assert set(MODEL_FACTORIES) == {
        "randomforest", "xgboost", "logistic", "lstm", "charlstm",
    }


def test_registry_has_param_distributions():
    # tune=True가 모든 모델에서 동작하려면 탐색 공간이 있어야 한다
    for key in MODEL_FACTORIES:
        assert DEFAULT_PARAM_DISTRIBUTIONS.get(key), f"{key} 탐색 공간 없음"


def test_create_model_unknown_type():
    with pytest.raises(ValueError, match="지원하지 않는"):
        create_model("no-such-model")


def test_create_model_lstm_returns_wrapper():
    model = create_model("lstm", hidden_size=8)
    assert isinstance(model, LSTMClassifier)
    assert model.hidden_size == 8


def test_randomforest_default_has_leaf_limit():
    model = create_model("randomforest")
    assert model.get_params()["min_samples_leaf"] == 20
# ---------------------------------------------------------------------------
# LSTMClassifier sklearn 호환성 (RandomizedSearchCV가 요구하는 것들)
# ---------------------------------------------------------------------------

def test_lstm_sklearn_compat():
    m = LSTMClassifier(hidden_size=8, epochs=1)
    params = m.get_params()
    assert params["hidden_size"] == 8
    m2 = clone(m).set_params(epochs=2)
    assert m2.epochs == 2 and m2.hidden_size == 8


# ---------------------------------------------------------------------------
# 학습 파이프라인 (새 알고리즘 2종 중심)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_type,params", [
    ("logistic", {}),
    ("lstm", {"epochs": 2, "hidden_size": 8}),
])
def test_train_model(dataset, model_type, params):
    bundle = training.train_model(dataset, model_type=model_type, **params)
    assert bundle.model_type == model_type
    assert set(bundle.metrics) >= {"accuracy", "f1_macro", "n_train", "n_test"}
    assert 0.0 <= bundle.metrics["accuracy"] <= 1.0

    urls = ["https://newsite.example.com/home"]
    labels = bundle.predict_labels(urls)
    assert labels.shape == (1,)
    assert labels[0] in {"benign", "malware"}

    proba = bundle.predict_proba(urls)
    assert proba is not None
    assert set(proba.columns) == {"benign", "malware"}
    np.testing.assert_allclose(proba.iloc[0].sum(), 1.0, atol=1e-6)


def test_charlstm_char_bundle(tmp_path):
    """CharTokenizer + charlstm 학습→추론→저장/로딩 왕복."""
    from src.analyzers.url.features import CharTokenizer, canonicalize_url_for_tfidf

    n = 30
    benign = [f"https://site{i}.example.com/page{i}" for i in range(n)]
    risky = [
        f"http://198.51.100.{i}/login.verify.update/x{i}.exe?id={i}"
        for i in range(n)
    ]
    urls, labels = benign + risky, ["benign"] * n + ["malware"] * n

    tokenizer = CharTokenizer(max_len=64)
    x = tokenizer.transform([canonicalize_url_for_tfidf(u) for u in urls])
    assert x.shape == (2 * n, 64) and x.dtype == np.int32
    assert x.max() < tokenizer.vocab_size

    from src.analyzers.url.schemas import DataSet

    bundle = training.train_model(
        DataSet(x, labels, name="char-synthetic"),
        model_type="charlstm",
        kind="char",
        vectorizer=tokenizer,
        epochs=2,
        hidden_size=16,
        vocab_size=tokenizer.vocab_size,
    )
    assert bundle.kind == "char"

    test_urls = ["https://newsite.example.com/home", ""]
    labels_pred = bundle.predict_labels(test_urls)
    assert labels_pred.shape == (2,)

    path = bundle.save(tmp_path / "charlstm.joblib")
    loaded = ModelBundle.load(path)
    np.testing.assert_array_equal(
        loaded.predict_labels(test_urls), bundle.predict_labels(test_urls)
    )


def test_bundle_save_load_roundtrip(dataset, tmp_path):
    bundle = training.train_model(
        dataset, model_type="lstm", epochs=2, hidden_size=8
    )
    path = bundle.save(tmp_path / "lstm.joblib")
    loaded = ModelBundle.load(path)

    urls = [
        "https://site0.example.com/page0",
        "http://198.51.100.0/login.verify.update/x0.exe?id=0",
    ]
    np.testing.assert_array_equal(
        loaded.predict_labels(urls), bundle.predict_labels(urls)
    )


# ---------------------------------------------------------------------------
# prediction 모듈 (최종 출력 형식)
# ---------------------------------------------------------------------------

def test_analyze_urls_verdict_format(dataset):
    bundle = training.train_model(dataset, model_type="logistic")
    urls = [
        "https://site1.example.com/page1",
        "http://198.51.100.1/login.verify.update/x1.exe?id=1",
    ]
    result = prediction.analyze_urls(bundle, urls)
    assert set(result) == set(urls)
    assert set(result.values()) <= {"위험", "안전"}

    detail = prediction.predict_urls(bundle, urls)
    assert len(detail) == 2
    for row in detail:
        assert {"url", "label", "verdict", "risk_score", "proba"} <= set(row)
        assert 0.0 <= row["risk_score"] <= 1.0
