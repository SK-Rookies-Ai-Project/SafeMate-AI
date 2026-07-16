"""터미널에서 URL을 입력받아 charLSTM 모델로 즉석 예측하는 임시 스크립트.

사용:
    uv run scripts/predict_url_cli.py                 # 기본: url_char_model.joblib
    uv run scripts/predict_url_cli.py models/url_char_model.joblib

빈 줄 또는 Ctrl-D(Ctrl-C)로 종료.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analyzers.url.constants import MODELS_DIR
from src.analyzers.url.schemas import ModelBundle


def main():
    model_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1
        else MODELS_DIR / "url_char_model.joblib"
    )
    bundle = ModelBundle.load(model_path)
    print(f"모델 로딩 완료: {model_path.name} ({bundle.model_type})")
    print("URL을 입력하세요 (빈 줄로 종료)\n")

    while True:
        try:
            url = input("url> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not url:
            break
        proba = bundle.predict_proba([url]).iloc[0]
        label = bundle.predict_labels([url])[0]
        detail = "  ".join(f"{c} {p:.1%}" for c, p in proba.items())
        print(f"  → {label}  ({detail})\n")


if __name__ == "__main__":
    main()
