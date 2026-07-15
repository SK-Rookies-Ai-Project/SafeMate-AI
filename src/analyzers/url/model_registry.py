from typing import Any
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import RandomizedSearchCV
from sklearn.preprocessing import LabelEncoder
''' 
---------------------------------------------------------------------------

 모델 레지스트리 (가변 모듈 선택식)
 학습에 사용될 모델과 파라메터 튜닝에 사용될 탐색공간정의
 ---------------------------------------------------------------------------
'''
def _make_randomforest(random_state: int, **params : Any):
    defaults = dict(n_estimators=300, n_jobs=-1)
    defaults.update(params)
    return RandomForestClassifier(random_state=random_state, **defaults)


def _make_xgboost(random_state: int, **params:Any):
    try:
        from xgboost import XGBClassifier
    except ImportError as e:
        raise ImportError(
            "xgboost가 설치되어 있지 않습니다: pip install xgboost"
        ) from e
    defaults = dict(n_estimators=300, tree_method="hist", n_jobs=-1)
    defaults.update(params)
    return XGBClassifier(random_state=random_state, **defaults)


MODEL_FACTORIES = {
    "randomforest": _make_randomforest,
    "xgboost": _make_xgboost,
}

# tune=True일 때 RandomizedSearchCV에 쓰는 기본 탐색 공간
DEFAULT_PARAM_DISTRIBUTIONS = {
    "randomforest": {
        "n_estimators": [100, 200, 300, 500],
        "max_depth": [None, 10, 20, 40],
        "min_samples_split": [2, 5, 10],
        "min_samples_leaf": [1, 2, 4],
        "max_features": ["sqrt", "log2"],
    },
    "xgboost": {
        "n_estimators": [100, 200, 300, 500],
        "max_depth": [3, 5, 7, 10],
        "learning_rate": [0.01, 0.05, 0.1, 0.3],
        "subsample": [0.7, 0.85, 1.0],
        "colsample_bytree": [0.7, 0.85, 1.0],
    },
}


def create_model(model_type: str, random_state: int = 42, **params):
    """레지스트리에서 이름으로 모델 생성."""
    if model_type not in MODEL_FACTORIES:
        raise ValueError(
            f"지원하지 않는 model_type: {model_type!r} "
            f"(사용 가능: {sorted(MODEL_FACTORIES)})"
        )
    return MODEL_FACTORIES[model_type](random_state, **params)