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
    x = features.clean_feature_matrix(df[features.FEATURE_NAMES].values)

    y = df[LABEL_COLUMN].tolist

    return DataSet(
        x=x,
        y=y,
        name=path.stem,
        random_state=random_state
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