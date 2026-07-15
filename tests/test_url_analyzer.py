"""메인 진입 파일(src/analyzers/url_analyzer.py) 통합 테스트.

실데이터(All.csv)가 필요한 테스트는 파일이 없는 환경에서 자동 skip된다.
"""

import pandas as pd
import pytest

from src.analyzers import url_analyzer
from src.analyzers.url import FEATURE_NAMES, LABEL_COLUMN, make_feature_dataset
from src.analyzers.url.constants import ALL_CSV, RISK_VERDICT, SAFE_VERDICT
from src.analyzers.url.training import train_model

needs_all_csv = pytest.mark.skipif(
    not ALL_CSV.exists(), reason=f"학습 데이터 없음: {ALL_CSV}"
)


@pytest.fixture(scope="module")
def bundle():
    benign = [f"https://www.site{i}.com/news-{i}.html" for i in range(30)]
    malicious = [
        f"http://10.0.{i}.1/secure-login/verify.php?acc=a{i}b&token={'x' * 30}"
        for i in range(30)
    ]
    ds = make_feature_dataset(benign + malicious, ["정상"] * 30 + ["악성"] * 30)
    return train_model(ds, n_estimators=30)


def test_analyze_urls_entry(bundle):
    urls = ["https://www.site1.com/news-1.html"]
    result = url_analyzer.analyze_urls(urls, bundle=bundle)
    assert result[urls[0]] in {RISK_VERDICT, SAFE_VERDICT}


def test_analyze_urls_detail_entry(bundle):
    [res] = url_analyzer.analyze_urls_detail(
        ["http://10.0.1.1/secure-login/verify.php?a=1"], bundle=bundle
    )
    assert {"url", "label", "verdict", "risk_score", "reasons"} <= set(res)


def test_load_model_roundtrip(tmp_path, bundle):
    path = bundle.save(tmp_path / "m.joblib")
    loaded = url_analyzer.load_model(path)
    urls = ["https://www.site2.com/news-2.html"]
    assert url_analyzer.analyze_urls(urls, bundle=loaded) == url_analyzer.analyze_urls(
        urls, bundle=bundle
    )


def test_analyze_urls_via_model_path(tmp_path, bundle):
    path = bundle.save(tmp_path / "m.joblib")
    result = url_analyzer.analyze_urls(
        ["https://www.site3.com/news-3.html"], model_path=path
    )
    assert len(result) == 1


@needs_all_csv
def test_feature_names_match_training_csv():
    # FEATURE_NAMES가 어긋나면 train/serve가 조용히 불일치한다 — 헤더로 고정
    header = pd.read_csv(ALL_CSV, nrows=0).columns.tolist()
    assert header == FEATURE_NAMES + [LABEL_COLUMN]


@needs_all_csv
def test_train_default_model_smoke(tmp_path):
    bundle = url_analyzer.train_default_model(
        nrows=2000, save_path=tmp_path / "default.joblib"
    )
    assert (tmp_path / "default.joblib").exists()
    assert "accuracy" in bundle.metrics
