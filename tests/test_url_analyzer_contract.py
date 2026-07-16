import json

import pytest

from src.analyzers import url_analyzer
from src.analyzers.url import training


@pytest.fixture(scope="module")
def url_bundle():
    benign = [
        f"https://site{i}.example.com/help/page{i}"
        for i in range(20)
    ]
    risky = [
        f"http://198.51.100.{i}/secure-login/verify/update{i}.exe?id={i}"
        for i in range(20)
    ]
    labels = ["benign"] * len(benign) + ["malware"] * len(risky)
    dataset = training.make_feature_dataset(benign + risky, labels)
    return training.train_model(dataset, model_type="logistic")


def _assert_contract(result):
    assert set(result) == {
        "status",
        "url",
        "label",
        "risk_score",
        "signals",
        "features",
        "model_version",
        "error",
    }
    assert result["label"] in {
        "benign",
        "suspicious",
        "malicious",
        "unknown",
    }
    assert result["model_version"] == "url-v1"
    json.dumps(result, ensure_ascii=False)


def test_analyze_url_benign_contract(url_bundle):
    result = url_analyzer.analyze_url(
        "https://www.example.com/login", bundle=url_bundle
    )

    _assert_contract(result)
    assert result["status"] == "success"
    assert result["error"] is None
    assert 0.0 <= result["risk_score"] <= 1.0
    assert result["features"]
    assert all(
        {"name", "raw_value", "normalized_value", "contribution"} <= set(row)
        for row in result["features"]
    )
    assert all(row["contribution"] is None for row in result["features"])


def test_analyze_url_suspicious_contract(url_bundle):
    result = url_analyzer.analyze_url(
        "http://198.51.100.8/secure-login/verify/update8.exe?id=8",
        bundle=url_bundle,
    )

    _assert_contract(result)
    assert result["status"] == "success"
    assert result["label"] in {"suspicious", "malicious"}
    assert result["signals"]


def test_analyze_url_tfidf_contract_reports_tfidf_features():
    benign = [f"https://safe{i}.example.com/home" for i in range(12)]
    risky = [f"http://evil{i}.example.ru/login/verify?id={i}" for i in range(12)]
    labels = ["benign"] * len(benign) + ["malicious"] * len(risky)
    dataset, vectorizer = training.make_tfidf_dataset(
        benign + risky,
        labels=labels,
        min_df=1,
        ngram_range=(3, 4),
    )
    bundle = training.train_model(
        dataset,
        model_type="logistic",
        kind="tfidf",
        vectorizer=vectorizer,
    )

    result = url_analyzer.analyze_url(
        "http://evil99.example.ru/login/verify?id=99",
        bundle=bundle,
    )

    _assert_contract(result)
    assert result["features"]
    assert all(row["name"].startswith("TF-IDF ngram: ") for row in result["features"])
    assert all(row["raw_value"] >= 0.0 for row in result["features"])


def test_analyze_url_invalid_contract_without_loading_model():
    result = url_analyzer.analyze_url("not a url")

    _assert_contract(result)
    assert result["status"] == "error"
    assert result["label"] == "unknown"
    assert result["risk_score"] is None
    assert result["features"] == []
    assert result["error"]
