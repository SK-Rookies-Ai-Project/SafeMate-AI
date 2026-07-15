from typing import Any
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import RandomizedSearchCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
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


def _make_logistic(random_state: int, **params: Any):
    # feature 스케일이 제각각이라 스케일링 없이는 수렴하지 않음
    # (with_mean=False: tfidf 희소행렬도 그대로 받기 위해)
    defaults = dict(max_iter=5000)
    defaults.update(params)
    return make_pipeline(
        StandardScaler(with_mean=False),
        LogisticRegression(random_state=random_state, **defaults),
    )


class LSTMClassifier(BaseEstimator, ClassifierMixin):
    """feature 행렬을 시퀀스로 보고 학습하는 PyTorch LSTM 분류기.

    각 행(feature 벡터)을 길이 d(feature 수)의 1차원 시퀀스로 취급한다.
    sklearn 호환 인터페이스(fit/predict/predict_proba)라서 기존
    train_model / ModelBundle 파이프라인에 그대로 들어간다.
    """

    def __init__(self, hidden_size=64, num_layers=1, dropout=0.0,
                 epochs=10, batch_size=64, lr=1e-3, random_state=42):
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.random_state = random_state

    @staticmethod
    def _torch():
        try:
            import torch
            from torch import nn
        except ImportError as e:
            raise ImportError(
                "torch가 설치되어 있지 않습니다: pip install torch"
            ) from e
        return torch, nn

    def _to_tensor(self, x, torch):
        if hasattr(x, "toarray"):  # scipy sparse (tfidf)
            x = x.toarray()
        x = np.asarray(x, dtype=np.float32)
        x = (x - self._mean_) / self._std_
        # (n, seq_len=d, input_size=1)
        return torch.from_numpy(x).unsqueeze(-1)

    def fit(self, x, y):
        torch, nn = self._torch()
        torch.manual_seed(self.random_state)

        self.classes_, y_idx = np.unique(y, return_inverse=True)
        raw = x.toarray() if hasattr(x, "toarray") else np.asarray(x)
        raw = raw.astype(np.float32)
        self._mean_ = raw.mean(axis=0)
        self._std_ = raw.std(axis=0)
        self._std_[self._std_ == 0] = 1.0

        xt = self._to_tensor(x, torch)
        yt = torch.from_numpy(y_idx.astype(np.int64))

        lstm = nn.LSTM(
            input_size=1,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout if self.num_layers > 1 else 0.0,
            batch_first=True,
        )
        head = nn.Linear(self.hidden_size, len(self.classes_))
        self.model_ = nn.ModuleDict({"lstm": lstm, "head": head})

        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.lr)
        loss_fn = nn.CrossEntropyLoss()
        dataset = torch.utils.data.TensorDataset(xt, yt)
        loader = torch.utils.data.DataLoader(
            dataset, batch_size=self.batch_size, shuffle=True,
            generator=torch.Generator().manual_seed(self.random_state),
        )

        self.model_.train()
        for _ in range(self.epochs):
            for xb, yb in loader:
                optimizer.zero_grad()
                loss = loss_fn(self._forward(xb), yb)
                loss.backward()
                optimizer.step()
        return self

    def _forward(self, xb):
        _, (h_n, _) = self.model_["lstm"](xb)
        return self.model_["head"](h_n[-1])  # 마지막 layer의 hidden state

    def predict_proba(self, x):
        torch, _ = self._torch()
        self.model_.eval()
        with torch.no_grad():
            logits = self._forward(self._to_tensor(x, torch))
            return torch.softmax(logits, dim=1).numpy()

    def predict(self, x):
        return self.classes_[self.predict_proba(x).argmax(axis=1)]


def _make_lstm(random_state: int, **params: Any):
    defaults = dict(hidden_size=64, epochs=10)
    defaults.update(params)
    return LSTMClassifier(random_state=random_state, **defaults)


MODEL_FACTORIES = {
    "randomforest": _make_randomforest,
    "xgboost": _make_xgboost,
    "logistic": _make_logistic,
    "lstm": _make_lstm,
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
    # logistic은 Pipeline이라 파라미터에 step 접두사가 붙는다
    "logistic": {
        "logisticregression__C": [0.01, 0.1, 1.0, 10.0, 100.0],
        "logisticregression__class_weight": [None, "balanced"],
    },
    "lstm": {
        "hidden_size": [32, 64, 128],
        "num_layers": [1, 2],
        "epochs": [5, 10, 20],
        "lr": [1e-3, 3e-3, 1e-2],
        "batch_size": [32, 64, 128],
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