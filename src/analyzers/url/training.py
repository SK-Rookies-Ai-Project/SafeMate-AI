"""CSV 로딩과 모델 학습 (Feature 모델 / TF-IDF 모델, 하이퍼파라미터 튜닝).

모델은 MODEL_FACTORIES 레지스트리에서 이름으로 선택한다(가변 모듈 선택식).
xgboost는 미설치 환경에서도 나머지가 동작하도록 지연 임포트한다.

사용 예:
    from src.analyzers.url import training

    ds = training.load_feature_csv()                       # All.csv → DataSet
    bundle = training.train_model(ds, model_type="randomforest", tune=True)
    bundle.save("models/url_feature_rf.joblib")
"""

from typing import Optional

from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import RandomizedSearchCV
from sklearn.preprocessing import LabelEncoder

from src.analyzers.url.schemas import DataSet, ModelBundle
from src.analyzers.url.datasets import (
    load_feature_csv,
    load_url_csv,
    make_feature_dataset,
    make_tfidf_dataset,
)
from src.analyzers.url.features import (
    build_tfidf_vectorizer,
    reduce_tfidf_dimensions,
)
from src.analyzers.url.model_registry import (
    DEFAULT_PARAM_DISTRIBUTIONS,
    MODEL_FACTORIES,
    create_model,
)


# ---------------------------------------------------------------------------
# 학습 / 하이퍼파라미터 튜닝
# ---------------------------------------------------------------------------

def tune_hyperparameters(
    model,
    dataset: DataSet,
    param_distributions: Optional[dict] = None,
    model_type: str = "",
    n_iter: int = 20,
    cv: int = 3,
    scoring: str = "f1_macro",
):
    """RandomizedSearchCV로 하이퍼파라미터 탐색. (best_model, best_params) 반환."""
    if param_distributions is None:
        param_distributions = DEFAULT_PARAM_DISTRIBUTIONS.get(model_type, {})
    if not param_distributions:
        raise ValueError(f"{model_type!r}의 탐색 공간이 없습니다.")
    search = RandomizedSearchCV(
        model,
        param_distributions,
        n_iter=n_iter,
        cv=cv,
        scoring=scoring,
        random_state=dataset.random_state,
        n_jobs=-1,
    )
    search.fit(dataset.x, dataset.y)
    return search.best_estimator_, search.best_params_


def train_model(
    dataset: DataSet,
    model_type: str = "randomforest",
    kind: str = "feature",
    vectorizer=None,
    tune: bool = False,
    tune_kwargs: Optional[dict] = None,
    test_size: float = 0.2,
    **model_params,
) -> ModelBundle:
    """DataSet으로 모델을 학습해 ModelBundle로 반환.

    holdout(test_size)으로 평가 지표를 계산한 뒤 전체 데이터로 재학습한다.

    Args:
        dataset: x, y가 채워진 DataSet.
        model_type: MODEL_FACTORIES의 키
            ('randomforest', 'xgboost', 'logistic', 'lstm').
        kind: 'feature' 또는 'tfidf' (추론 시 전처리 방법 결정).
        vectorizer: kind='tfidf'일 때 학습에 사용한 vectorizer.
        tune: True면 학습 전 RandomizedSearchCV로 하이퍼파라미터 탐색.
        tune_kwargs: tune_hyperparameters에 넘길 인자 (n_iter, cv 등).
    """
    if dataset.y is None:
        raise ValueError("학습에는 라벨(y)이 필요합니다.")
    if kind == "tfidf" and vectorizer is None:
        raise ValueError("kind='tfidf'는 vectorizer가 필요합니다.")

    encoder = LabelEncoder()
    y = encoder.fit_transform(dataset.y)
    encoded = DataSet(dataset.x, y, dataset.name, dataset.random_state)

    model = create_model(model_type, dataset.random_state, **model_params)
    best_params = dict(model_params)
    if tune:
        model, tuned = tune_hyperparameters(
            model, encoded, model_type=model_type, **(tune_kwargs or {})
        )
        best_params.update(tuned)

    # holdout 평가
    train_ds, test_ds = encoded.split(test_size=test_size)
    model.fit(train_ds.x, train_ds.y)
    pred = model.predict(test_ds.x)
    metrics = {
        "accuracy": float(accuracy_score(test_ds.y, pred)),
        "f1_macro": float(f1_score(test_ds.y, pred, average="macro")),
        "n_train": len(train_ds),
        "n_test": len(test_ds),
    }

    # 전체 데이터로 재학습한 최종 모델
    model.fit(encoded.x, encoded.y)

    return ModelBundle(
        model=model,
        kind=kind,
        model_type=model_type,
        vectorizer=vectorizer,
        feature_names=(
            list(dataset.x.columns) if hasattr(dataset.x, "columns") else None
        ),
        label_encoder=encoder,
        params=best_params,
        metrics=metrics,
        name=f"{dataset.name}-{model_type}",
    )
