from pathlib import Path

import pandas as pd
import pytest

from src.analyzers.url import features, training
from src.analyzers.url.schemas import ModelBundle


@pytest.fixture
def sample_urls_and_labels():
    urls = [
        "https://example.com/home",
        "http://safe-site.org/about",
        "https://mybank.com/login",
        "http://docs.python.org/3/",
        "https://github.com/features",
        "http://news.ycombinator.com/",
        "http://secure-login-paypal.verify-user.ru/confirm?account=1",
        "http://198.51.100.77/update.exe",
        "http://free-bonus-offer.example.net/login?password=1234",
        "http://xn--pple-43d.com/signin",
        "javascript:alert(1)",
        "http://bad-site.com/verify/account/update",
    ]
    labels = [
        "benign",
        "benign",
        "benign",
        "benign",
        "benign",
        "benign",
        "malicious",
        "malicious",
        "malicious",
        "malicious",
        "malicious",
        "malicious",
    ]
    return urls, labels


def test_load_url_csv_cleans_wrapped_quotes(tmp_path):
    csv_path = tmp_path / "urls.csv"
    pd.DataFrame(
        {
            "url": ["'https://example.com'", '"http://test.org/a"'],
            "label": ["benign", "malicious"],
        }
    ).to_csv(csv_path, index=False)

    urls, labels = training.load_url_csv(csv_path)

    assert urls == ["https://example.com", "http://test.org/a"]
    assert labels == ["benign", "malicious"]


def test_load_feature_csv_creates_dataset_and_cleans_values(tmp_path, sample_urls_and_labels):
    urls, labels = sample_urls_and_labels
    df = features.build_url_dataset(urls, labels=labels)

    # Inject values that should be cleaned by clean_feature_matrix.
    # Use float-like ratio columns to avoid pandas int column upcast errors.
    df.loc[0, "pathurlRatio"] = float("inf")
    df.loc[1, "ArgUrlRatio"] = float("nan")

    csv_path = tmp_path / "all_like.csv"
    df.to_csv(csv_path, index=False)

    ds = training.load_feature_csv(csv_path)

    assert ds.name == "all_like"
    assert len(ds) == len(urls)
    assert ds.n_features == len(features.FEATURE_NAMES)
    assert isinstance(ds.y, list)
    assert ds.y[0] in {"benign", "malicious"}
    assert ds.x.loc[0, "pathurlRatio"] == -1.0
    assert ds.x.loc[1, "ArgUrlRatio"] == -1.0


def test_make_feature_dataset_builds_expected_shape(sample_urls_and_labels):
    urls, labels = sample_urls_and_labels

    ds = training.make_feature_dataset(urls, labels=labels, name="feature-ds")

    assert ds.name == "feature-ds"
    assert len(ds) == len(urls)
    assert ds.n_features == len(features.FEATURE_NAMES)
    assert list(ds.x.columns) == list(features.FEATURE_NAMES)


def test_canonicalize_url_for_tfidf_removes_transport_noise():
    variants = [
        "www.naver.com",
        "https://www.naver.com/",
        "http://naver.com/",
    ]

    assert {
        features.canonicalize_url_for_tfidf(url)
        for url in variants
    } == {"naver.com"}
    assert (
        features.canonicalize_url_for_tfidf("https://www.google.com/search?q=Hi")
        == "google.com/search?q=hi"
    )


def test_importance_tuning_params_drops_low_importance_features(sample_urls_and_labels):
    if not hasattr(training, "importance_tuning_params"):
        pytest.skip("importance_tuning_params is not available in this training module version")

    urls, labels = sample_urls_and_labels
    ds = training.make_feature_dataset(urls, labels=labels)

    reduced, dropped = training.importance_tuning_params(
        ds,
        model_type="randomforest",
        drop_n=5,
    )

    assert len(dropped) == 5
    assert reduced.n_features == ds.n_features - 5
    assert all(col not in reduced.x.columns for col in dropped)


def test_train_model_feature_flow_train_predict_save_load(tmp_path, sample_urls_and_labels):
    urls, labels = sample_urls_and_labels
    ds = training.make_feature_dataset(urls, labels=labels)

    # Keep core train/predict/save/load path compatible across module revisions.
    bundle = training.train_model(ds, model_type="randomforest", kind="feature", n_estimators=30, max_depth=6)

    assert bundle.kind == "feature"
    assert bundle.model_type == "randomforest"
    assert "accuracy" in bundle.metrics
    assert "f1_macro" in bundle.metrics

    preds = bundle.predict_labels(urls[:3])
    assert len(preds) == 3

    save_path = tmp_path / "url_feature_bundle.joblib"
    saved = bundle.save(save_path)
    assert Path(saved).exists()

    loaded = ModelBundle.load(save_path)
    loaded_preds = loaded.predict_labels(urls[:3])
    assert len(loaded_preds) == 3


def test_train_model_tfidf_flow_train_predict(sample_urls_and_labels):
    urls, labels = sample_urls_and_labels
    ds_tfidf, vec = training.make_tfidf_dataset(urls, labels=labels, min_df=1, ngram_range=(1, 2))

    bundle = training.train_model(
        ds_tfidf,
        model_type="randomforest",
        kind="tfidf",
        vectorizer=vec,
        n_estimators=20,
        max_depth=5,
    )

    assert bundle.kind == "tfidf"
    assert bundle.vectorizer is not None
    assert len(bundle.predict_labels(urls[:2])) == 2


def test_exception_handling_paths(sample_urls_and_labels):
    urls, labels = sample_urls_and_labels

    ds_no_label = training.make_feature_dataset(urls, labels=None)
    with pytest.raises(ValueError, match=r"라벨\(y\)이 필요"):
        training.train_model(ds_no_label)

    ds_tfidf, _ = training.make_tfidf_dataset(urls, labels=labels)
    with pytest.raises(ValueError, match="vectorizer가 필요"):
        training.train_model(ds_tfidf, kind="tfidf", vectorizer=None)

    ds_feature = training.make_feature_dataset(urls, labels=labels)
    model = training.create_model("randomforest", random_state=42, n_estimators=10)
    with pytest.raises(ValueError, match="탐색 공간"):
        training.tune_hyperparameters(model, ds_feature, model_type="unknown", n_iter=1, cv=2)
