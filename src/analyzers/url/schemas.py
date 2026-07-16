"""데이터셋/모델 번들 스키마 클래스."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple, Union

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from src.analyzers.url import features


@dataclass
class DataSet:
    """전처리된 학습/추론용 데이터셋.

    x: feature 행렬 (DataFrame 또는 scipy sparse / ndarray)
    y: 라벨 배열 (추론용이면 None)
    name: 데이터셋 이름 (예: 'all-features', 'binary-tfidf')
    random_state: split 등에 쓰는 시드
    """

    x: Any
    y: Optional[Sequence] = None
    name: str = ""
    random_state: int = 42

    @property
    def n_features(self) -> int:
        return self.x.shape[1]

    def __len__(self) -> int:
        return self.x.shape[0]

    def split(self, test_size: float = 0.2) -> Tuple["DataSet", "DataSet"]:
        """학습/평가 데이터셋으로 분할 (라벨이 있으면 층화 추출)."""
        if self.y is None:
            raise ValueError("y가 없는 데이터셋은 split할 수 없습니다.")
        x_train, x_test, y_train, y_test = train_test_split(
            self.x,
            self.y,
            test_size=test_size,
            random_state=self.random_state,
            stratify=self.y,
        )
        return (
            DataSet(x_train, y_train, f"{self.name}-train", self.random_state),
            DataSet(x_test, y_test, f"{self.name}-test", self.random_state),
        )


@dataclass
class ModelBundle:
    """학습된 모델 + 전처리기 + 메타데이터 묶음. joblib으로 저장/로딩.

    kind: 'feature'(유형1, lexical feature) 또는 'tfidf'(유형2)
    """

    model: Any
    kind: str
    model_type: str = ""                       # 'randomforest', 'xgboost', ...
    vectorizer: Any = None                     # kind='tfidf'일 때 필수
    feature_names: Optional[list] = None       # kind='feature'일 때 컬럼 순서
    label_encoder: Any = None                  # y 인코딩에 쓴 LabelEncoder
    params: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    name: str = ""

    def transform(self, urls: Sequence[str]):
        """URL 배열 → 이 모델이 받는 feature 행렬 (학습 때와 동일한 전처리)."""
        if self.kind == "feature":
            df = features.clean_feature_matrix(features.build_url_dataset(urls))
            if self.feature_names:
                df = df[self.feature_names]
            return df
        if self.kind == "tfidf":
            if self.vectorizer is None:
                raise ValueError("tfidf 번들에 vectorizer가 없습니다.")
            return self.vectorizer.transform(
                [features.canonicalize_url_for_tfidf(u) for u in urls]
            )
        raise ValueError(f"알 수 없는 kind: {self.kind!r}")

    def predict_labels(self, urls: Sequence[str]) -> np.ndarray:
        """URL 배열 → 원본 라벨 문자열 예측."""
        pred = self.model.predict(self.transform(urls))
        if self.label_encoder is not None:
            pred = self.label_encoder.inverse_transform(pred)
        return np.asarray(pred)

    def predict_proba(self, urls: Sequence[str]) -> Optional[pd.DataFrame]:
        """클래스별 확률 (컬럼=원본 라벨). 모델이 지원하지 않으면 None."""
        if not hasattr(self.model, "predict_proba"):
            return None
        proba = self.model.predict_proba(self.transform(urls))
        classes = self.model.classes_
        if self.label_encoder is not None:
            classes = self.label_encoder.inverse_transform(classes)
        return pd.DataFrame(proba, columns=classes)

    def save(self, path: Union[str, Path]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, path: Union[str, Path]) -> "ModelBundle":
        bundle = joblib.load(path)
        if not isinstance(bundle, cls):
            raise TypeError(f"{path}는 ModelBundle이 아닙니다: {type(bundle)}")
        return bundle
