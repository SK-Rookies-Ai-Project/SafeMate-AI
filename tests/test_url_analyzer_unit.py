from pathlib import Path

from src.analyzers import url_analyzer


def test_analyze_url_invalid_input_does_not_load_model(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("model loading should not be called")

    monkeypatch.setattr(url_analyzer, "get_default_model", fail_if_called)

    result = url_analyzer.analyze_url("not a url")

    assert result["status"] == "error"
    assert result["url"] == "not a url"
    assert result["label"] == "unknown"
    assert result["risk_score"] is None
    assert result["signals"] == []
    assert result["features"] == []
    assert result["model_version"] == "url-v1"
    assert result["error"]


def test_analyze_url_returns_missing_model_error(monkeypatch, tmp_path):
    missing_model = tmp_path / "missing.joblib"

    def raise_missing_model(path):
        assert path == missing_model
        raise FileNotFoundError(path)

    monkeypatch.setattr(url_analyzer, "get_default_model", raise_missing_model)

    result = url_analyzer.analyze_url(
        "https://example.com/login",
        model_path=missing_model,
    )

    assert result == {
        "status": "error",
        "url": "https://example.com/login",
        "label": "unknown",
        "risk_score": None,
        "signals": [],
        "features": [],
        "model_version": "url-v1",
        "error": "url model is not available",
    }


def test_analyze_url_uses_provided_bundle_without_loading_default(monkeypatch):
    bundle = object()
    expected = {
        "status": "success",
        "url": "https://example.com",
        "label": "benign",
        "risk_score": 0.01,
        "signals": [],
        "features": [],
        "model_version": "url-v1",
        "error": None,
    }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("default model should not be loaded")

    def fake_analyze_url(received_bundle, received_url):
        assert received_bundle is bundle
        assert received_url == "https://example.com"
        return expected

    monkeypatch.setattr(url_analyzer, "get_default_model", fail_if_called)
    monkeypatch.setattr(url_analyzer.prediction, "analyze_url", fake_analyze_url)

    assert url_analyzer.analyze_url("https://example.com", bundle=bundle) == expected


def test_get_default_model_caches_by_path_string(monkeypatch, tmp_path):
    url_analyzer._load_model_cached.cache_clear()
    calls = []

    def fake_load_model(path):
        calls.append(path)
        return {"path": path, "calls": len(calls)}

    monkeypatch.setattr(url_analyzer, "load_model", fake_load_model)

    model_path = tmp_path / "url_feature_model.joblib"
    first = url_analyzer.get_default_model(model_path)
    second = url_analyzer.get_default_model(Path(model_path))

    assert first is second
    assert calls == [str(model_path)]

    url_analyzer._load_model_cached.cache_clear()


def test_batch_helpers_load_default_model_and_delegate(monkeypatch, tmp_path):
    bundle = object()
    urls = ["https://example.com", "http://198.51.100.1/login"]
    model_path = tmp_path / "model.joblib"

    def fake_get_default_model(received_path):
        assert received_path == model_path
        return bundle

    def fake_analyze_urls(received_bundle, received_urls):
        assert received_bundle is bundle
        assert received_urls is urls
        return {"https://example.com": "safe"}

    monkeypatch.setattr(url_analyzer, "get_default_model", fake_get_default_model)
    monkeypatch.setattr(url_analyzer.prediction, "analyze_urls", fake_analyze_urls)

    result = url_analyzer.analyze_urls(urls, model_path=model_path)

    assert result == {"https://example.com": "safe"}


def test_analyze_urls_detail_uses_given_bundle(monkeypatch):
    bundle = object()
    urls = ["https://example.com"]
    expected = [{"url": "https://example.com", "label": "benign"}]

    def fail_if_called(*args, **kwargs):
        raise AssertionError("default model should not be loaded")

    def fake_predict_urls(received_bundle, received_urls):
        assert received_bundle is bundle
        assert received_urls is urls
        return expected

    monkeypatch.setattr(url_analyzer, "get_default_model", fail_if_called)
    monkeypatch.setattr(url_analyzer.prediction, "predict_urls", fake_predict_urls)

    assert url_analyzer.analyze_urls_detail(urls, bundle=bundle) == expected
