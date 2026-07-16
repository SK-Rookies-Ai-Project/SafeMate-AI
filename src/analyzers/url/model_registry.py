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
                 epochs=10, batch_size=64, lr=1e-3, device="auto",
                 random_state=42):
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.device = device  # 'auto' | 'cpu' | 'cuda'
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

    @staticmethod
    def _prep(x):
        # 희소행렬은 행 슬라이싱 가능한 CSR로 유지하고, 밀집 입력만 배열화한다.
        # 전체 toarray()는 tfidf(수십만 차원 × 수백만 행)에서 OOM이라 금지.
        if hasattr(x, "toarray"):  # scipy sparse (tfidf)
            return x.tocsr()
        return np.asarray(x, dtype=np.float32)

    def _fit_stats(self, x):
        if hasattr(x, "toarray"):
            # 밀도화 없이 E[x²]-E[x]²로 열별 통계 계산
            mean = np.asarray(x.mean(axis=0), dtype=np.float32).ravel()
            mean_sq = np.asarray(
                x.multiply(x).mean(axis=0), dtype=np.float32
            ).ravel()
            std = np.sqrt(np.maximum(mean_sq - mean ** 2, 0.0))
        else:
            mean = x.mean(axis=0)
            std = x.std(axis=0)
        std[std == 0] = 1.0
        self._mean_, self._std_ = mean, std

    def _batch_tensor(self, xb, torch):
        # 배치 단위로만 밀도화 + 표준화
        if hasattr(xb, "toarray"):
            xb = xb.toarray().astype(np.float32, copy=False)
        xb = (xb - self._mean_) / self._std_
        # (n, seq_len=d, input_size=1)
        return torch.from_numpy(xb).unsqueeze(-1)

    def _resolve_device(self, torch):
        if self.device == "auto":
            return torch.device(
                "cuda" if torch.cuda.is_available() else "cpu"
            )
        return torch.device(self.device)

    def fit(self, x, y):
        torch, nn = self._torch()
        torch.manual_seed(self.random_state)
        dev = self._resolve_device(torch)

        self.classes_, y_idx = np.unique(y, return_inverse=True)
        x = self._prep(x)
        self._fit_stats(x)
        yt = torch.from_numpy(y_idx.astype(np.int64))

        lstm = nn.LSTM(
            input_size=1,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout if self.num_layers > 1 else 0.0,
            batch_first=True,
        )
        head = nn.Linear(self.hidden_size, len(self.classes_))
        self.model_ = nn.ModuleDict({"lstm": lstm, "head": head}).to(dev)

        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.lr)
        loss_fn = nn.CrossEntropyLoss()
        # 전체 텐서 대신 인덱스만 섞고 배치를 그때그때 밀도화한다
        loader = torch.utils.data.DataLoader(
            torch.arange(x.shape[0]), batch_size=self.batch_size, shuffle=True,
            generator=torch.Generator().manual_seed(self.random_state),
        )

        self.model_.train()
        for _ in range(self.epochs):
            for bidx in loader:
                xb = self._batch_tensor(x[bidx.numpy()], torch)
                optimizer.zero_grad()
                loss = loss_fn(self._forward(xb.to(dev)), yt[bidx].to(dev))
                loss.backward()
                optimizer.step()
        # 저장(pickle)·추론 호환성을 위해 학습 후 CPU로 이동
        self.model_.to("cpu")
        return self

    def _forward(self, xb):
        _, (h_n, _) = self.model_["lstm"](xb)
        return self.model_["head"](h_n[-1])  # 마지막 layer의 hidden state

    def predict_proba(self, x, batch_size: int = 8192):
        # 한 번에 forward하면 LSTM 중간 활성값(n × seq × hidden)이
        # 수십 GB가 될 수 있어 반드시 배치로 나눠 추론한다
        torch, _ = self._torch()
        self.model_.eval()
        x = self._prep(x)
        outs = []
        with torch.no_grad():
            for i in range(0, x.shape[0], batch_size):
                xb = self._batch_tensor(x[i:i + batch_size], torch)
                outs.append(torch.softmax(self._forward(xb), dim=1))
        return torch.cat(outs).numpy()

    def predict(self, x):
        return self.classes_[self.predict_proba(x).argmax(axis=1)]


class CharLSTMClassifier(BaseEstimator, ClassifierMixin):
    """URL을 문자 id 시퀀스로 받아 학습하는 문자 단위 PyTorch LSTM 분류기.

    입력은 CharTokenizer(features.py)가 만드는 (n, max_len) int 행렬이다
    (0=패딩). embedding → LSTM → 마지막 유효 문자의 hidden state → linear.
    TF-IDF/SVD 없이 문자 패턴을 직접 학습한다.
    """

    def __init__(self, vocab_size=96, embed_dim=32, hidden_size=128,
                 num_layers=1, dropout=0.0, epochs=5, batch_size=1024,
                 lr=1e-3, device="auto", random_state=42):
        self.vocab_size = vocab_size  # CharTokenizer.vocab_size와 일치해야 함
        self.embed_dim = embed_dim
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.device = device  # 'auto' | 'cpu' | 'cuda'
        self.random_state = random_state

    _torch = staticmethod(LSTMClassifier._torch)
    _resolve_device = LSTMClassifier._resolve_device

    def _forward(self, xb, torch):
        # 패딩을 무시하도록 pack해서 각 URL의 마지막 실제 문자 hidden을 쓴다
        emb = self.model_["embed"](xb)
        lengths = (xb != 0).sum(dim=1).clamp(min=1).cpu()
        packed = torch.nn.utils.rnn.pack_padded_sequence(
            emb, lengths, batch_first=True, enforce_sorted=False
        )
        _, (h_n, _) = self.model_["lstm"](packed)
        return self.model_["head"](h_n[-1])

    def fit(self, x, y):
        torch, nn = self._torch()
        torch.manual_seed(self.random_state)
        dev = self._resolve_device(torch)

        self.classes_, y_idx = np.unique(y, return_inverse=True)
        # int32로 들고 있다가 배치에서만 int64 텐서로 변환 (전체 int64는 2배 메모리)
        x = np.ascontiguousarray(x, dtype=np.int32)
        yt = torch.from_numpy(y_idx.astype(np.int64))

        embed = nn.Embedding(self.vocab_size, self.embed_dim, padding_idx=0)
        lstm = nn.LSTM(
            input_size=self.embed_dim,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout if self.num_layers > 1 else 0.0,
            batch_first=True,
        )
        head = nn.Linear(self.hidden_size, len(self.classes_))
        self.model_ = nn.ModuleDict(
            {"embed": embed, "lstm": lstm, "head": head}
        ).to(dev)

        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.lr)
        loss_fn = nn.CrossEntropyLoss()
        loader = torch.utils.data.DataLoader(
            torch.arange(x.shape[0]), batch_size=self.batch_size, shuffle=True,
            generator=torch.Generator().manual_seed(self.random_state),
        )

        self.model_.train()
        for _ in range(self.epochs):
            for bidx in loader:
                xb = torch.from_numpy(
                    x[bidx.numpy()].astype(np.int64)
                ).to(dev)
                optimizer.zero_grad()
                loss = loss_fn(self._forward(xb, torch), yt[bidx].to(dev))
                loss.backward()
                optimizer.step()
        # 저장(pickle)·추론 호환성을 위해 학습 후 CPU로 이동
        self.model_.to("cpu")
        return self

    def predict_proba(self, x, batch_size: int = 8192):
        torch, _ = self._torch()
        dev = self._resolve_device(torch)
        self.model_.to(dev).eval()
        x = np.ascontiguousarray(x, dtype=np.int32)
        outs = []
        with torch.no_grad():
            for i in range(0, x.shape[0], batch_size):
                xb = torch.from_numpy(
                    x[i:i + batch_size].astype(np.int64)
                ).to(dev)
                logits = self._forward(xb, torch)
                outs.append(torch.softmax(logits, dim=1).cpu())
        self.model_.to("cpu")
        return torch.cat(outs).numpy()

    def predict(self, x):
        return self.classes_[self.predict_proba(x).argmax(axis=1)]


def _make_lstm(random_state: int, **params: Any):
    defaults = dict(hidden_size=64, epochs=10)
    defaults.update(params)
    return LSTMClassifier(random_state=random_state, **defaults)


def _make_charlstm(random_state: int, **params: Any):
    defaults = dict(hidden_size=128, epochs=5)
    defaults.update(params)
    return CharLSTMClassifier(random_state=random_state, **defaults)


MODEL_FACTORIES = {
    "randomforest": _make_randomforest,
    "xgboost": _make_xgboost,
    "logistic": _make_logistic,
    "lstm": _make_lstm,
    "charlstm": _make_charlstm,
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
    "charlstm": {
        "embed_dim": [16, 32, 64],
        "hidden_size": [64, 128, 256],
        "num_layers": [1, 2],
        "epochs": [3, 5, 10],
        "lr": [1e-3, 3e-3],
        "batch_size": [512, 1024],
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