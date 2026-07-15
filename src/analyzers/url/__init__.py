"""URL 분석 서브패키지: 전처리(feature/TF-IDF), 데이터셋, 학습, 예측."""

from src.analyzers.url.constants import (
    ALL_CSV,
    BENIGN_LABELS,
    LABEL_COLUMN,
    MODELS_DIR,
    RISK_VERDICT,
    SAFE_VERDICT,
    URL_BINARY_CSV,
)
from src.analyzers.url.features import (
    FEATURE_NAMES,
    build_tfidf_vectorizer,
    build_url_dataset,
    clean_feature_matrix,
    clean_url,
    extract_url_features,
    normalize_url,
)
from src.analyzers.url.schemas import DataSet, ModelBundle
from src.analyzers.url.training import (
    MODEL_FACTORIES,
    create_model,
    load_feature_csv,
    load_url_csv,
    make_feature_dataset,
    make_tfidf_dataset,
    train_model,
    tune_hyperparameters,
)

try:
    from src.analyzers.url.prediction import analyze_url, analyze_urls, predict_urls
except ModuleNotFoundError:
    analyze_url = None
    analyze_urls = None
    predict_urls = None

__all__ = [
    "ALL_CSV",
    "BENIGN_LABELS",
    "LABEL_COLUMN",
    "MODELS_DIR",
    "RISK_VERDICT",
    "SAFE_VERDICT",
    "URL_BINARY_CSV",
    "FEATURE_NAMES",
    "build_tfidf_vectorizer",
    "build_url_dataset",
    "clean_feature_matrix",
    "clean_url",
    "extract_url_features",
    "normalize_url",
    "DataSet",
    "ModelBundle",
    "MODEL_FACTORIES",
    "create_model",
    "load_feature_csv",
    "load_url_csv",
    "make_feature_dataset",
    "make_tfidf_dataset",
    "train_model",
    "tune_hyperparameters",
]

if analyze_urls is not None:
    __all__.extend(["analyze_url", "analyze_urls", "predict_urls"])
