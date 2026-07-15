"""URL 학습 데이터 로딩과 DataSet 생성."""

from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

import pandas as pd

from src.analyzers.url import features
from src.analyzers.url.constants import (
    ALL_CSV,
    LABEL_COLUMN,
    URL_BINARY_CSV,
)
from src.analyzers.url.schemas import DataSet


def load_feature_csv(
    path: Union[str, Path] = ALL_CSV,
    nrows: Optional[int] = None,
    random_state: int = 42,
) -> DataSet:
    """All.csv의 구조 Feature와 라벨을 DataSet으로 반환한다."""


    return DataSet(
    )


def load_url_csv(
    path: Union[str, Path] = URL_BINARY_CSV,
    nrows: Optional[int] = None,
) -> Tuple[list[str], list]:
    """URL 원문과 라벨을 CSV에서 읽는다."""

    return 


def make_feature_dataset(
    urls: Sequence[str],
    labels: Optional[Sequence] = None,
    name: str = "url-features",
    random_state: int = 42,
) -> DataSet:
    """URL 원문을 구조 Feature DataSet으로 변환한다."""

    return DataSet(
       
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

    return 