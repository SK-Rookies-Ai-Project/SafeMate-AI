"""URL 학습 데이터 로딩과 DataSet 생성."""

import logging
import zlib
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import tldextract
from sklearn.model_selection import train_test_split

from src.analyzers.url import features
from src.analyzers.url.constants import (
    ALL_CSV,
    LABEL_COLUMN,
    URL_BINARY_CSV,
)
from src.analyzers.url.schemas import DataSet

log = logging.getLogger(__name__)

# 오프라인 고정: 패키지 내장 PSL 스냅샷만 사용 (네트워크 fetch 없음 → 재현 가능)
_tld_extract = tldextract.TLDExtract(suffix_list_urls=())


def registered_domain(host: str) -> str:
    """host의 등록 도메인(eTLD+1). IP·localhost 등 PSL 밖이면 host 그대로."""
    return _tld_extract(host).top_domain_under_public_suffix or host


def dedup_group_split(
    urls: Sequence[str],
    y,
    test_size: float = 0.05,
    random_state: int = 42,
    dedup: bool = True,
    split: str = "group",
) -> Tuple[list, list, np.ndarray, np.ndarray]:
    """canonical 중복을 제거하고 등록 도메인 단위로 train/test를 나눈다.

    랜덤 URL split은 test URL 대부분이 train과 같은 도메인이라
    '새 URL 일반화'가 아닌 '본 도메인 암기'를 측정하게 된다.
    split='group'은 등록 도메인(eTLD+1)의 해시로 행을 배정해
    train/test 간 도메인이 겹치지 않게 한다. 해시 배정이라 같은
    random_state면 nrows 표본이 달라져도 도메인의 소속이 안 바뀐다.
    dedup=True면 canonical 형태가 같은 중복 행과, canonical이 같은데
    라벨이 충돌하는 행(라벨 노이즈)을 먼저 제거한다.

    Returns:
        (urls_train, urls_test, y_train, y_test) — urls는 원문 그대로.
    """
    if split not in ("group", "random"):
        raise ValueError(f"지원하지 않는 split: {split!r} (group 또는 random)")

    urls = pd.Series(urls, dtype=object).astype(str)
    y = np.asarray(y)
    canonical = urls.map(features.canonicalize_url_for_tfidf)

    if dedup:
        before = len(urls)
        n_dup = int(canonical.duplicated().sum())
        keep = ~canonical.duplicated().values
        # canonical이 같은데 라벨이 다른 그룹은 전부 제거
        pairs = pd.DataFrame({"c": canonical.values, "y": y}).drop_duplicates()
        conflicts = set(pairs.loc[pairs["c"].duplicated(), "c"])
        if conflicts:
            keep &= ~canonical.isin(conflicts).values
        urls, canonical, y = urls[keep], canonical[keep], y[keep]
        log.info(
            "dedup: %s행 → %s행 (canonical 중복 %s, 라벨충돌 그룹 %s)",
            f"{before:,}", f"{len(urls):,}", f"{n_dup:,}", len(conflicts),
        )

    if split == "random":
        return train_test_split(
            urls.tolist(), y, test_size=test_size,
            random_state=random_state, stratify=y,
        )

    hosts = canonical.str.extract(r"^([^/:?]*)", expand=False)
    domains = hosts.map(
        {h: registered_domain(h) for h in hosts.unique()}
    )
    # 도메인 해시 < threshold → test. salt로 random_state를 섞어 재현 가능.
    salt = f"{random_state}:".encode()
    threshold = int(test_size * 2 ** 32)
    unique_domains = domains.unique()
    to_test = {
        d: zlib.crc32(salt + d.encode()) < threshold for d in unique_domains
    }
    mask_test = domains.map(to_test).values
    log.info(
        "group split: 도메인 %s개, test 행 %.2f%% (목표 %.2f%%)",
        f"{len(unique_domains):,}", mask_test.mean() * 100, test_size * 100,
    )
    return (
        urls[~mask_test].tolist(),
        urls[mask_test].tolist(),
        y[~mask_test],
        y[mask_test],
    )


# schemas.py의 DataSet 클래스 활용
def load_feature_csv(
    path: Union[str, Path] = ALL_CSV,
    nrows: Optional[int] = None,
    random_state: int = 42,
) -> DataSet:
    """All.csv의 구조 Feature와 라벨을 DataSet으로 반환한다."""

    # Path 객체로 변환
    path = Path(path)

    # 파일 존재 여부 확인
    if not path.exists():
        raise FileNotFoundError(f"Feature CSV를 찾을 수 없습니다: {path}")

    # CSV 파일 읽기
    df = pd.read_csv(path, nrows=nrows)

    # Missing columns 확인
    missing_columns =[]

    for column in features.FEATURE_NAMES:
        if column not in df.columns:
            missing_columns.append(column)

    # raise 메소드로 missing columns 확인
    if missing_columns:
        raise ValueError(f"Feature CSV에 필요한 컬럼이 없습니다: {missing_columns}")

    if LABEL_COLUMN not in df.columns:
        raise ValueError(f"Feature CSV에 라벨 컬럼이 없습니다: {LABEL_COLUMN}")

    # clean_feature_matrix 함수활용으로 x 정리
    '''
    def clean_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """모델 입력용 정리: ±inf → NaN → -1 로 치환 (NaN을 못 받는 모델 대비)."""
    return df.replace([float("inf"), float("-inf")], float("nan")).fillna(-1.0)
    '''
    X = features.clean_feature_matrix(df[features.FEATURE_NAMES])

    y = df[LABEL_COLUMN].tolist()

    return DataSet(
        x=X,
        y=y,
        name=path.stem,
        random_state=random_state
    )

# TF-IDF 사용을 위한 데이터
def load_url_csv(
    path: Union[str, Path] = URL_BINARY_CSV,
    nrows: Optional[int] = None,
) -> Tuple[list[str], list]:
    """URL 원문과 라벨을 CSV에서 읽는다."""

    # Path 객체로 변환
    path = Path(path)

    # 파일 존재 여부 확인
    if not path.exists():
        raise FileNotFoundError(f"URL CSV를 찾을 수 없습니다: {path}")

    df = pd.read_csv(path, nrows=nrows)

    # 데이터 확인
    if df.shape[1] < 2:
        raise ValueError(f"URL CSV가 비어 있습니다: {path}")

    urls = [features.clean_url(url) for url in df.iloc[:, 0].astype(str)]
    labels = df.iloc[:, 1].tolist()

    return urls, labels


def make_feature_dataset(
    urls: Sequence[str],
    labels: Optional[Sequence] = None,
    name: str = "url-features",
    random_state: int = 42,
) -> DataSet:
    """URL 원문을 구조 Feature DataSet으로 변환한다."""

    feature_frame = features.build_url_dataset(urls)

    # clean_feature_matrix 함수 활용으로 x 정리
    X = features.clean_feature_matrix(feature_frame)

    # labels가 None이면 y도 None으로 설정
    y = (
        list(labels)
        if labels is not None
        else None
    )

    return DataSet(
        x=X,
        y=y,
        name=name,
        random_state=random_state
    )


def make_tfidf_dataset(
    urls: Sequence[str],
    labels: Optional[Sequence] = None,
    name: str = "url-tfidf",
    random_state: int = 42,
    vectorizer=None,
    **vectorizer_params,
):
    """URL 원문을 TF-IDF DataSet으로 변환한다.

    vectorizer가 없으면 학습용으로 새로 fit한다.
    vectorizer가 있으면 추론용으로 transform만 수행한다.
    """

    cleaned_urls = [
        features.canonicalize_url_for_tfidf(url)
        for url in urls
    ]

    # vectorizer가 없으면 새로 fit, 있으면 transform만 수행
    if vectorizer is None:
        vectorizer = features.build_tfidf_vectorizer(**vectorizer_params)
        X = vectorizer.fit_transform(cleaned_urls)
    else:
        X = vectorizer.transform(cleaned_urls)

    # labels가 None이면 y도 None으로 설정
    y = (
        list(labels)
        if labels is not None
        else None
    )

    dataset = DataSet(
        x=X,
        y=y,
        name=name,
        random_state=random_state
    )


    return dataset,vectorizer
