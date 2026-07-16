"""URL 정규화/전처리/특징 추출.

두 가지 전처리 유형을 제공한다:
- 유형1: 학습 데이터(All.csv, ISCX-URL-2016)와 동일한 스키마의 lexical feature
  추출 → `build_url_dataset`
- 유형2: TF-IDF 벡터화 → `build_tfidf_vectorizer` + vectorizer.fit/transform

All.csv의 관측된 규칙을 따른다:
- tld 는 문자열이 아니라 TLD 길이(숫자)
- Entropy_* 는 Shannon entropy를 log2(길이)로 나눈 정규화값(0~1).
  길이 0(컴포넌트 없음) → -1, 길이 1 → NaN
- avgpathtokenlen: 경로 토큰 없음 → NaN
- NumberRate_Extension: 확장자 없음 → NaN (다른 NumberRate_* 는 -1)
- isPortEighty: 포트 80 명시 → 0, 그 외 → -1 (학습 데이터 값이 {-1, 0} 뿐)
- ISIpAddressInDomainName: 학습 데이터 전체가 -1 이므로 상수 -1 로 맞춤
- 그 외 정의 불가능한 값 → -1

일부 feature(ArgLen, spcharUrl, delimeter_*, charcompace 등)는 원본 추출
도구가 공개되지 않아 표준 정의로 근사한다. 정확한 재현이 필요하면 raw URL
데이터(url_binary_dataset.csv)에서 이 모듈로 학습 데이터를 재생성할 것.
"""

import math
import re
from collections import Counter
from typing import Iterable, Optional, Sequence

from urllib.parse import urlparse

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from src.analyzers.url.constants import (
    DELIMITERS,
    EXECUTABLE_EXTENSIONS,
    LABEL_COLUMN,
    SENSITIVE_WORDS,
    VOWELS,
)

_IP_PATTERN = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+")

# All.csv 헤더와 동일한 컬럼 순서 (라벨 컬럼 제외 79개)
FEATURE_NAMES = [
    "Querylength",
    "domain_token_count",
    "path_token_count",
    "avgdomaintokenlen",
    "longdomaintokenlen",
    "avgpathtokenlen",
    "tld",
    "charcompvowels",
    "charcompace",
    "ldl_url",
    "ldl_domain",
    "ldl_path",
    "ldl_filename",
    "ldl_getArg",
    "dld_url",
    "dld_domain",
    "dld_path",
    "dld_filename",
    "dld_getArg",
    "urlLen",
    "domainlength",
    "pathLength",
    "subDirLen",
    "fileNameLen",
    "this.fileExtLen",
    "ArgLen",
    "pathurlRatio",
    "ArgUrlRatio",
    "argDomanRatio",
    "domainUrlRatio",
    "pathDomainRatio",
    "argPathRatio",
    "executable",
    "isPortEighty",
    "NumberofDotsinURL",
    "ISIpAddressInDomainName",
    "CharacterContinuityRate",
    "LongestVariableValue",
    "URL_DigitCount",
    "host_DigitCount",
    "Directory_DigitCount",
    "File_name_DigitCount",
    "Extension_DigitCount",
    "Query_DigitCount",
    "URL_Letter_Count",
    "host_letter_count",
    "Directory_LetterCount",
    "Filename_LetterCount",
    "Extension_LetterCount",
    "Query_LetterCount",
    "LongestPathTokenLength",
    "Domain_LongestWordLength",
    "Path_LongestWordLength",
    "sub-Directory_LongestWordLength",
    "Arguments_LongestWordLength",
    "URL_sensitiveWord",
    "URLQueries_variable",
    "spcharUrl",
    "delimeter_Domain",
    "delimeter_path",
    "delimeter_Count",
    "NumberRate_URL",
    "NumberRate_Domain",
    "NumberRate_DirectoryName",
    "NumberRate_FileName",
    "NumberRate_Extension",
    "NumberRate_AfterPath",
    "SymbolCount_URL",
    "SymbolCount_Domain",
    "SymbolCount_Directoryname",
    "SymbolCount_FileName",
    "SymbolCount_Extension",
    "SymbolCount_Afterpath",
    "Entropy_URL",
    "Entropy_Domain",
    "Entropy_DirectoryName",
    "Entropy_Filename",
    "Entropy_Extension",
    "Entropy_Afterpath",
]


# ---------------------------------------------------------------------------
# 저수준 헬퍼
# ---------------------------------------------------------------------------

def _entropy(text: str) -> float:
    """정규화 Shannon entropy (H / log2(len)). 길이 0 → -1, 길이 1 → NaN."""
    if not text:
        return -1.0
    if len(text) == 1:
        return float("nan")
    counts = Counter(text)
    total = len(text)
    h = -sum((c / total) * math.log2(c / total) for c in counts.values())
    return h / math.log2(total)


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else -1.0


def _digit_count(text: str) -> int:
    return sum(ch.isdigit() for ch in text)


def _letter_count(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


def _symbol_count(text: str) -> int:
    """영숫자가 아닌 문자(기호) 개수. 컴포넌트 없음 → -1."""
    if not text:
        return -1
    return sum(not ch.isalnum() for ch in text)


def _number_rate(text: str, missing: float = -1.0) -> float:
    return _digit_count(text) / len(text) if text else missing


def _count_or_missing(text: str, count: int) -> int:
    return count if text else -1


def _delimiter_count(text: str) -> int:
    return sum(ch in DELIMITERS for ch in text)


def _ldl_count(text: str) -> int:
    """letter-digit-letter 패턴 개수 (예: 'a1b'). 문자 치환 난독화 지표."""
    return sum(
        text[i - 1].isalpha() and text[i].isdigit() and text[i + 1].isalpha()
        for i in range(1, len(text) - 1)
    )


def _dld_count(text: str) -> int:
    """digit-letter-digit 패턴 개수 (예: '1a2')."""
    return sum(
        text[i - 1].isdigit() and text[i].isalpha() and text[i + 1].isdigit()
        for i in range(1, len(text) - 1)
    )


def _longest_word_length(text: str) -> int:
    """영숫자 단어 중 가장 긴 길이. 단어가 없으면 -1."""
    words = _WORD_PATTERN.findall(text)
    return max(len(w) for w in words) if words else -1


def _character_continuity_rate(domain: str) -> float:
    """문자/숫자/기호 각 유형별 최장 연속 구간 길이의 합 / 도메인 길이."""
    if not domain:
        return -1.0

    def char_class(ch: str) -> str:
        if ch.isalpha():
            return "letter"
        if ch.isdigit():
            return "digit"
        return "symbol"

    longest = {"letter": 0, "digit": 0, "symbol": 0}
    run_class, run_len = None, 0
    for ch in domain:
        cls = char_class(ch)
        run_len = run_len + 1 if cls == run_class else 1
        run_class = cls
        longest[cls] = max(longest[cls], run_len)
    return sum(longest.values()) / len(domain)


# ---------------------------------------------------------------------------
# URL 정규화
# ---------------------------------------------------------------------------

def clean_url(url: str) -> str:
    """입력 정리: 앞뒤 공백과 감싼 따옴표 제거."""
    return url.strip().strip("'\"")


def normalize_url(url: str) -> str:
    """스킴이 없는 URL도 urlparse가 hostname을 인식하도록 보정."""
    url = clean_url(url)
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "http://" + url
    return url


def canonicalize_url_for_tfidf(url: str) -> str:
    """Canonical text used by TF-IDF models for train/serve consistency.

    TF-IDF should learn domain, path, and query patterns instead of incidental
    transport spelling such as http vs https, leading www, or a root slash.
    """
    raw = clean_url(str(url)).lower()
    try:
        parsed = urlparse(normalize_url(raw))
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]

        port = ""
        try:
            parsed_port = parsed.port
        except ValueError:
            parsed_port = None
        if parsed_port and parsed_port not in {80, 443}:
            port = f":{parsed_port}"

        path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
        query = f"?{parsed.query}" if parsed.query else ""
        canonical = f"{host}{port}{path}{query}"
        return canonical or raw
    except Exception:
        return re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", raw).rstrip("/")


# ---------------------------------------------------------------------------
# 유형1 — lexical feature 추출
# ---------------------------------------------------------------------------

def extract_url_features(url: str) -> dict:
    """단일 URL에서 All.csv 스키마의 feature 79개를 추출해 dict로 반환.

    비정상 URL(잘못된 포트, 'javascript:' 등)도 예외 없이 처리한다 —
    해석 불가능한 컴포넌트는 없는 것으로 간주하고 나머지 feature를 계산한다.
    """
    raw = clean_url(url)
    parsed = urlparse(normalize_url(raw))
    # hostname/port는 lazy 파싱이라 'http://a.com:abc/' 같은 입력에서
    # 접근 시점에 ValueError를 던진다
    try:
        domain = parsed.hostname or ""
    except ValueError:
        domain = ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    path = parsed.path or ""
    query = parsed.query or ""
    after_path = query + (parsed.fragment or "")

    # path → 디렉터리 / 파일명 / 확장자 분해 (마지막 '/' 뒤 세그먼트를 파일명으로 간주)
    slash = path.rfind("/")
    directory = path[: slash + 1] if slash >= 0 else ""
    filename = path[slash + 1:] if slash >= 0 else path
    dot = filename.rfind(".")
    extension = filename[dot + 1:] if dot > 0 else ""

    domain_tokens = [t for t in domain.split(".") if t]
    path_tokens = [t for t in path.split("/") if t]
    arg_pairs = [p for p in query.split("&") if p]
    arg_values = [p.split("=", 1)[1] for p in arg_pairs if "=" in p]

    is_ip = bool(_IP_PATTERN.match(domain))
    tld_token = domain_tokens[-1] if domain_tokens and not is_ip else ""
    lower = raw.lower()

    return {
        "Querylength": len(query),
        "domain_token_count": len(domain_tokens),
        "path_token_count": len(path_tokens),
        "avgdomaintokenlen": (
            sum(map(len, domain_tokens)) / len(domain_tokens) if domain_tokens else -1.0
        ),
        "longdomaintokenlen": max(map(len, domain_tokens)) if domain_tokens else -1,
        "avgpathtokenlen": (
            sum(map(len, path_tokens)) / len(path_tokens)
            if path_tokens else float("nan")
        ),
        "tld": len(tld_token) if tld_token else -1,
        "charcompvowels": sum(ch in VOWELS for ch in raw),
        "charcompace": raw.count(" ") + lower.count("%20"),
        "ldl_url": _ldl_count(raw),
        "ldl_domain": _ldl_count(domain),
        "ldl_path": _ldl_count(path),
        "ldl_filename": _ldl_count(filename),
        "ldl_getArg": _ldl_count(query),
        "dld_url": _dld_count(raw),
        "dld_domain": _dld_count(domain),
        "dld_path": _dld_count(path),
        "dld_filename": _dld_count(filename),
        "dld_getArg": _dld_count(query),
        "urlLen": len(raw),
        "domainlength": len(domain),
        "pathLength": len(path),
        "subDirLen": len(directory),
        "fileNameLen": len(filename),
        "this.fileExtLen": len(extension),
        "ArgLen": len(query),
        "pathurlRatio": _safe_div(len(path), len(raw)),
        "ArgUrlRatio": _safe_div(len(query), len(raw)),
        "argDomanRatio": _safe_div(len(query), len(domain)),
        "domainUrlRatio": _safe_div(len(domain), len(raw)),
        "pathDomainRatio": _safe_div(len(path), len(domain)),
        "argPathRatio": _safe_div(len(query), len(path)),
        "executable": int(extension.lower() in EXECUTABLE_EXTENSIONS),
        # 학습 데이터 값이 {-1, 0} 뿐: 포트 80 명시 → 0, 그 외 → -1
        "isPortEighty": 0 if port == 80 else -1,
        "NumberofDotsinURL": raw.count("."),
        # 학습 데이터 전체가 -1 인 죽은 feature — 분포를 맞추기 위해 상수 -1
        "ISIpAddressInDomainName": -1,
        "CharacterContinuityRate": _character_continuity_rate(domain),
        "LongestVariableValue": max(map(len, arg_values)) if arg_values else -1,
        "URL_DigitCount": _digit_count(raw),
        "host_DigitCount": _digit_count(domain),
        "Directory_DigitCount": _count_or_missing(directory, _digit_count(directory)),
        "File_name_DigitCount": _count_or_missing(filename, _digit_count(filename)),
        "Extension_DigitCount": _count_or_missing(extension, _digit_count(extension)),
        "Query_DigitCount": _count_or_missing(query, _digit_count(query)),
        "URL_Letter_Count": _letter_count(raw),
        "host_letter_count": _letter_count(domain),
        "Directory_LetterCount": _count_or_missing(directory, _letter_count(directory)),
        "Filename_LetterCount": _count_or_missing(filename, _letter_count(filename)),
        "Extension_LetterCount": _count_or_missing(extension, _letter_count(extension)),
        "Query_LetterCount": _count_or_missing(query, _letter_count(query)),
        "LongestPathTokenLength": max(map(len, path_tokens)) if path_tokens else -1,
        "Domain_LongestWordLength": _longest_word_length(domain),
        "Path_LongestWordLength": _longest_word_length(path),
        "sub-Directory_LongestWordLength": _longest_word_length(directory),
        "Arguments_LongestWordLength": _longest_word_length(query),
        "URL_sensitiveWord": sum(w in lower for w in SENSITIVE_WORDS),
        "URLQueries_variable": len(arg_pairs),
        "spcharUrl": _symbol_count(raw),
        "delimeter_Domain": _delimiter_count(domain),
        "delimeter_path": _delimiter_count(path),
        "delimeter_Count": _delimiter_count(raw),
        "NumberRate_URL": _number_rate(raw),
        "NumberRate_Domain": _number_rate(domain),
        "NumberRate_DirectoryName": _number_rate(directory),
        "NumberRate_FileName": _number_rate(filename),
        # 확장자 없음 → NaN (학습 데이터 규칙)
        "NumberRate_Extension": _number_rate(extension, missing=float("nan")),
        "NumberRate_AfterPath": _number_rate(after_path),
        "SymbolCount_URL": _symbol_count(raw),
        "SymbolCount_Domain": _symbol_count(domain),
        "SymbolCount_Directoryname": _symbol_count(directory),
        "SymbolCount_FileName": _symbol_count(filename),
        "SymbolCount_Extension": _symbol_count(extension),
        "SymbolCount_Afterpath": _symbol_count(after_path),
        "Entropy_URL": _entropy(raw),
        "Entropy_Domain": _entropy(domain),
        "Entropy_DirectoryName": _entropy(directory),
        "Entropy_Filename": _entropy(filename),
        "Entropy_Extension": _entropy(extension),
        "Entropy_Afterpath": _entropy(after_path),
    }


def build_url_dataset(
    urls: Iterable[str],
    labels: Optional[Sequence] = None,
    include_url: bool = False,
) -> pd.DataFrame:
    """URL 배열을 All.csv 와 동일한 스키마의 DataFrame으로 변환.

    Args:
        urls: URL 문자열 배열.
        labels: 각 URL의 라벨. 지정하면 URL_Type_obf_Type 컬럼이 추가되어
            All.csv 와 동일한 80컬럼이 된다.
        include_url: True면 원본 URL을 `url` 컬럼으로 맨 앞에 추가(디버깅용).
    """
    urls = list(urls)
    if labels is not None and len(labels) != len(urls):
        raise ValueError(
            f"labels 길이({len(labels)})가 urls 길이({len(urls)})와 다릅니다."
        )
    rows = [extract_url_features(u) for u in urls]
    df = pd.DataFrame(rows, columns=FEATURE_NAMES)
    if labels is not None:
        df[LABEL_COLUMN] = list(labels)
    if include_url:
        df.insert(0, "url", urls)
    return df


def clean_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """모델 입력용 정리: ±inf → NaN → -1 로 치환 (NaN을 못 받는 모델 대비)."""
    return df.replace([float("inf"), float("-inf")], float("nan")).fillna(-1.0)


# ---------------------------------------------------------------------------
# 유형2 — TF-IDF 전처리
# ---------------------------------------------------------------------------

def build_tfidf_vectorizer(**overrides) -> TfidfVectorizer:
    """URL용 TF-IDF 벡터라이저 생성 (문자 n-gram 기반).

    학습 시 `vectorizer.fit_transform(urls)`, 추론 시 `vectorizer.transform(urls)`.
    """
    params = dict(
        analyzer="char_wb",
        ngram_range=(3, 5),
        min_df=2,
        max_features=100_000,
        lowercase=True,
    )
    params.update(overrides)
    return TfidfVectorizer(**params)
