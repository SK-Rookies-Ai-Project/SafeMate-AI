"""DataSet / 학습 / 예측 파이프라인 테스트 (합성 데이터 사용)."""

import numpy as np
import pytest

from src.analyzers.url import (
    DataSet,
    ModelBundle,
    RISK_VERDICT,
    SAFE_VERDICT,
    analyze_urls,
    create_model,
    make_feature_dataset,
    make_tfidf_dataset,
    predict_urls,
    train_model,
    tune_hyperparameters,
)

rng = np.random.default_rng(0)


def _synthetic_urls(n=40):
    """구분 가능한 신호를 가진 합성 URL: 악성은 IP+login+긴 쿼리."""
    benign = [
        f"https://www.site{i}.com/articles/news-{i}.html" for i in range(n)
    ]
    malicious = [
        f"http://10.0.{i}.{i%250}/secure-login/verify.php?acc=a{i}b{i}c&token={'x'*30}{i}"
        for i in range(n)
    ]
    urls = benign + malicious
    labels = ["정상"] * n + ["악성"] * n
    return urls, labels


@pytest.fixture(scope="module")
def feature_bundle():
    urls, labels = _synthetic_urls()
    ds = make_feature_dataset(urls, labels, name="synthetic")
    return train_model(ds, model_type="randomforest", n_estimators=30)


# ---------------------------------------------------------------------------
# DataSet
# ---------------------------------------------------------------------------

def test_dataset_properties():
    urls, labels = _synthetic_urls(10)
    ds = make_feature_dataset(urls, labels, name="synthetic", random_state=7)
    assert ds.n_features == 79
    assert len(ds) == 20
    assert ds.name == "synthetic"
    assert ds.random_state == 7
    assert not ds.x.isna().any().any()  # 모델 입력은 NaN 없음


def test_dataset_split_stratified():
    urls, labels = _synthetic_urls(20)
    ds = make_feature_dataset(urls, labels)
    train, test = ds.split(test_size=0.25)
    assert len(train) == 30 and len(test) == 10
    assert sorted(set(test.y)) == ["악성", "정상"]  # 층화 확인
    assert train.name.endswith("-train")


def test_dataset_split_requires_labels():
    ds = make_feature_dataset(["https://a.com"])
    with pytest.raises(ValueError):
        ds.split()


# ---------------------------------------------------------------------------
# 학습 (feature / tfidf / 모델 선택 / 튜닝)
# ---------------------------------------------------------------------------

def test_train_feature_model(feature_bundle):
    assert feature_bundle.kind == "feature"
    assert feature_bundle.metrics["accuracy"] >= 0.9  # 신호가 뚜렷한 합성 데이터
    assert feature_bundle.feature_names is not None


def test_train_tfidf_model():
    urls, labels = _synthetic_urls(30)
    ds, vec = make_tfidf_dataset(urls, labels, min_df=1)
    bundle = train_model(ds, model_type="randomforest", kind="tfidf",
                         vectorizer=vec, n_estimators=30)
    assert bundle.kind == "tfidf"
    preds = bundle.predict_labels(["http://10.0.3.3/secure-login/verify.php?acc=a1b2c"])
    assert preds[0] in {"정상", "악성"}


def test_tfidf_kind_requires_vectorizer():
    urls, labels = _synthetic_urls(5)
    ds, _ = make_tfidf_dataset(urls, labels, min_df=1)
    with pytest.raises(ValueError):
        train_model(ds, kind="tfidf")


def test_create_model_registry():
    assert create_model("randomforest").__class__.__name__ == "RandomForestClassifier"
    with pytest.raises(ValueError):
        create_model("no-such-model")


def test_xgboost_training():
    pytest.importorskip("xgboost")
    urls, labels = _synthetic_urls(20)
    ds = make_feature_dataset(urls, labels)
    bundle = train_model(ds, model_type="xgboost", n_estimators=20)
    assert bundle.model_type == "xgboost"
    assert bundle.metrics["accuracy"] >= 0.9


def test_hyperparameter_tuning():
    urls, labels = _synthetic_urls(20)
    ds = make_feature_dataset(urls, labels)
    bundle = train_model(
        ds,
        model_type="randomforest",
        tune=True,
        tune_kwargs=dict(
            param_distributions={"n_estimators": [10, 20], "max_depth": [3, 5]},
            n_iter=2,
            cv=2,
        ),
    )
    assert "n_estimators" in bundle.params
    assert bundle.params["n_estimators"] in (10, 20)


# ---------------------------------------------------------------------------
# 예측 / 출력 형식 / 저장·로딩
# ---------------------------------------------------------------------------

def test_analyze_urls_output_format(feature_bundle):
    urls = [
        "https://www.site999.com/articles/news-1.html",
        "http://10.0.9.9/secure-login/verify.php?acc=a9b9c&token=" + "x" * 30,
    ]
    result = analyze_urls(feature_bundle, urls)
    assert set(result.keys()) == set(urls)
    assert set(result.values()) <= {RISK_VERDICT, SAFE_VERDICT}
    assert result[urls[1]] == RISK_VERDICT


def test_predict_urls_detail(feature_bundle):
    [res] = predict_urls(
        feature_bundle,
        ["http://10.0.9.9/secure-login/verify.php?acc=a9b9c&token=" + "x" * 30],
    )
    assert res["verdict"] == RISK_VERDICT
    assert 0.0 <= res["risk_score"] <= 1.0
    assert res["reasons"]  # IP 도메인, 민감 단어 등 근거가 나와야 함


def test_bundle_save_load_roundtrip(tmp_path, feature_bundle):
    path = feature_bundle.save(tmp_path / "bundle.joblib")
    loaded = ModelBundle.load(path)
    url = "https://www.site1.com/articles/news-1.html"
    assert loaded.predict_labels([url]) == feature_bundle.predict_labels([url])


def test_analyze_urls_empty_list(feature_bundle):
    assert analyze_urls(feature_bundle, []) == {}


def test_analyze_urls_duplicates_collapse(feature_bundle):
    url = "https://www.site1.com/articles/news-1.html"
    result = analyze_urls(feature_bundle, [url, url])
    assert list(result.keys()) == [url]  # dict 출력이라 중복 URL은 1개로 합쳐짐


def test_analyze_urls_with_malformed_url(feature_bundle):
    # 배열에 비정상 URL이 섞여도 전체 분석이 죽지 않아야 한다
    urls = ["javascript:alert(1)", "http://a.com:abc/x", "https://www.site1.com/a.html"]
    result = analyze_urls(feature_bundle, urls)
    assert set(result.keys()) == set(urls)


def test_predict_without_proba_falls_back():
    class NoProbaModel:
        def predict(self, x):
            return ["악성"] * x.shape[0]

    bundle = ModelBundle(model=NoProbaModel(), kind="feature", model_type="stub")
    [res] = predict_urls(bundle, ["https://example.com"], with_reasons=False)
    assert res["verdict"] == RISK_VERDICT
    assert res["risk_score"] == 1.0  # 확률 미지원 → 위험 예측이면 1.0


def test_risk_reasons_rules(feature_bundle):
    cases = {
        "http://attacker.com/@www.bank.com/": "@",
        "http://example.com/" + "a" * 120: "깁니다",
        "http://xn--wgbl6a.com/x": "퓨니코드",
    }
    for url, keyword in cases.items():
        [res] = predict_urls(feature_bundle, [url])
        assert any(keyword in r for r in res["reasons"]), (url, res["reasons"])


def test_non_http_scheme_forced_risky(feature_bundle):
    risky = ["javascript:alert(1)", "data:text/html;base64,AAAA", "ftp://host/file.exe"]
    result = analyze_urls(feature_bundle, risky)
    assert all(v == RISK_VERDICT for v in result.values()), result
    [res] = predict_urls(feature_bundle, ["javascript:alert(1)"])
    assert res["risk_score"] == 1.0
    assert any("스킴" in r for r in res["reasons"])


def test_host_port_not_mistaken_for_scheme(feature_bundle):
    # 'example.com:8080'의 'example.com'을 스킴으로 오인하면 안 된다
    from src.analyzers.url.prediction import non_http_scheme

    assert non_http_scheme("example.com:8080/x") is None
    assert non_http_scheme("https://a.com") is None
    assert non_http_scheme("JAVASCRIPT:alert(1)") == "javascript"
    assert non_http_scheme("ftp://host/f") == "ftp"


def test_split_is_deterministic():
    urls, labels = _synthetic_urls(15)
    a = make_feature_dataset(urls, labels, random_state=7).split()
    b = make_feature_dataset(urls, labels, random_state=7).split()
    assert a[1].x.index.tolist() == b[1].x.index.tolist()
