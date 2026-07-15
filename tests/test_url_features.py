"""All.csv 스키마 feature 추출기 테스트."""

import math

import pytest

from src.analyzers.url import (
    FEATURE_NAMES,
    LABEL_COLUMN,
    build_url_dataset,
    extract_url_features,
)

SAMPLE = "http://www.example-site.com:80/download/files/setup1a.exe?id=abc123&token=x9y"


def test_feature_names_count():
    assert len(FEATURE_NAMES) == 79
    assert LABEL_COLUMN == "URL_Type_obf_Type"
    assert LABEL_COLUMN not in FEATURE_NAMES


def test_all_features_present():
    feats = extract_url_features(SAMPLE)
    assert set(feats.keys()) == set(FEATURE_NAMES)


def test_basic_lengths_and_tokens():
    feats = extract_url_features(SAMPLE)
    assert feats["urlLen"] == len(SAMPLE)
    assert feats["domainlength"] == len("www.example-site.com")
    assert feats["domain_token_count"] == 3  # www / example-site / com
    assert feats["longdomaintokenlen"] == len("example-site")
    assert feats["tld"] == 3  # len('com') — 학습 데이터에서 tld는 TLD 길이
    assert feats["path_token_count"] == 3  # download / files / setup1a.exe
    assert feats["subDirLen"] == len("/download/files/")
    assert feats["fileNameLen"] == len("setup1a.exe")
    assert feats["this.fileExtLen"] == 3  # exe


def test_executable_and_port():
    feats = extract_url_features(SAMPLE)
    assert feats["executable"] == 1
    assert feats["isPortEighty"] == 0  # 학습 데이터 규칙: 포트 80 명시 → 0
    assert extract_url_features("https://a.com/x.html")["isPortEighty"] == -1
    assert extract_url_features("https://a.com/x.html")["executable"] == 0


def test_ip_domain_constant():
    # 학습 데이터 전체가 -1 이므로 IP 여부와 무관하게 -1
    assert extract_url_features("http://192.168.0.1/a")["ISIpAddressInDomainName"] == -1
    assert extract_url_features("http://192.168.0.1/a")["tld"] == -1  # IP → TLD 없음


def test_ldl_dld_counts():
    # 'a1b' → letter-digit-letter 1개, '1a2' → digit-letter-digit 1개
    feats = extract_url_features("http://a1b.com/1a2")
    assert feats["ldl_domain"] == 1
    assert feats["dld_path"] == 1


def test_query_variables():
    feats = extract_url_features(SAMPLE)
    assert feats["URLQueries_variable"] == 2
    assert feats["LongestVariableValue"] == len("abc123")
    assert feats["Querylength"] == len("id=abc123&token=x9y")


def test_ratios():
    feats = extract_url_features(SAMPLE)
    assert feats["pathurlRatio"] == pytest.approx(feats["pathLength"] / feats["urlLen"])
    assert feats["domainUrlRatio"] == pytest.approx(
        feats["domainlength"] / feats["urlLen"]
    )


def test_entropy_is_normalized():
    feats = extract_url_features(SAMPLE)
    assert 0.0 <= feats["Entropy_URL"] <= 1.0
    assert 0.0 <= feats["Entropy_Domain"] <= 1.0
    # 모든 문자가 다르면 정규화 엔트로피 == 1
    assert extract_url_features("http://abcd.ef")["Entropy_Domain"] == pytest.approx(1.0)


def test_missing_component_conventions():
    feats = extract_url_features("http://example.com")
    # 컴포넌트 없음 → -1
    assert feats["Entropy_Afterpath"] == -1.0
    assert feats["LongestVariableValue"] == -1
    assert feats["argPathRatio"] == -1.0
    assert feats["Query_DigitCount"] == -1
    # 확장자 없음 → NaN (학습 데이터 규칙)
    assert math.isnan(feats["NumberRate_Extension"])
    # 경로 토큰 없음 → NaN
    assert math.isnan(feats["avgpathtokenlen"])


def test_single_char_component_entropy_is_nan():
    # 길이 1 컴포넌트는 log2(1)=0 이라 학습 데이터에서 NaN
    feats = extract_url_features("http://example.com/a.b")
    assert math.isnan(feats["Entropy_Extension"])


def test_quoted_url_is_stripped():
    # url_binary_dataset.csv 형식: 'www.foo.com/...' 처럼 따옴표로 감싸짐
    feats = extract_url_features("'www.example.com/path'")
    assert feats["domainlength"] == len("www.example.com")


def test_build_dataset_inference_shape():
    df = build_url_dataset(["https://example.com", "http://a.com/x.exe"])
    assert list(df.columns) == FEATURE_NAMES  # 라벨/URL 없이 학습 X와 동일
    assert len(df) == 2


def test_build_dataset_with_labels_matches_training_schema():
    df = build_url_dataset(["https://example.com"], labels=["benign"])
    assert list(df.columns) == FEATURE_NAMES + [LABEL_COLUMN]  # All.csv와 동일
    assert df[LABEL_COLUMN].tolist() == ["benign"]


def test_build_dataset_include_url():
    df = build_url_dataset(["https://example.com"], include_url=True)
    assert df.columns[0] == "url"


def test_label_length_mismatch_raises():
    with pytest.raises(ValueError):
        build_url_dataset(["https://example.com"], labels=["benign", "phishing"])


# ---------------------------------------------------------------------------
# 비정상 입력 — 실사용에서 배열에 섞여 들어와도 예외 없이 처리해야 한다
# ---------------------------------------------------------------------------

MALFORMED_URLS = [
    "",                              # 빈 문자열
    "   ",                           # 공백만
    "http://a.com:abc/x",            # 숫자가 아닌 포트 → urlparse.port ValueError
    "javascript:alert(1)",           # 비HTTP 스킴 (스킴 보정 후 포트로 오인)
    "http://[::1]:8080/x",           # IPv6
    "http://한글도메인.한국/경로",     # 유니코드 도메인
    "http://" + "a" * 5000 + ".com",  # 초장문
    "////",
    "http://user:pass@host.com/x",   # userinfo 포함
]


@pytest.mark.parametrize("bad_url", MALFORMED_URLS)
def test_malformed_urls_do_not_raise(bad_url):
    feats = extract_url_features(bad_url)
    assert set(feats.keys()) == set(FEATURE_NAMES)


def test_malformed_port_treated_as_no_port():
    feats = extract_url_features("http://a.com:abc/x")
    assert feats["isPortEighty"] == -1


def test_malformed_urls_in_dataset():
    df = build_url_dataset(MALFORMED_URLS + ["https://example.com"])
    assert len(df) == len(MALFORMED_URLS) + 1
