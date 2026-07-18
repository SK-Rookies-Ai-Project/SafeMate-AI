"""터미널에서 URL을 입력받아 앙상블(charlstm + tfidf:logistic)로 예측하는 임시 스크립트.

가중치는 group split holdout에서 탐색한 최적값 0.5:0.5가 기본
(models/url_ensemble_char_tfidf.json 참고).

사용:
    uv run scripts/predict_url_cli.py
    uv run scripts/predict_url_cli.py --char-weight 0.75
    uv run scripts/predict_url_cli.py --char-model models/url_char_model.joblib \
        --second-model models/url_feature_model.joblib

빈 줄 또는 Ctrl-D(Ctrl-C)로 종료.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analyzers.url.constants import MODELS_DIR
from src.analyzers.url.schemas import ModelBundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--char-model", type=Path,
                        default=MODELS_DIR / "url_char_model.joblib")
    parser.add_argument("--second-model", type=Path,
                        default=MODELS_DIR / "url_tfidf_model.joblib")
    parser.add_argument("--char-weight", type=float, default=0.5,
                        help="char 모델 확률 가중치 (나머지는 second 모델)")
    args = parser.parse_args()
    if not 0 <= args.char_weight <= 1:
        parser.error("--char-weight는 0~1 사이여야 합니다.")

    char_bundle = ModelBundle.load(args.char_model)
    second_bundle = ModelBundle.load(args.second_model)
    classes = sorted(char_bundle.label_encoder.classes_)
    print(f"앙상블 로딩 완료: {args.char_model.name}({char_bundle.model_type}) "
          f"{args.char_weight:.2f} + {args.second_model.name}"
          f"({second_bundle.model_type}) {1 - args.char_weight:.2f}")
    print("URL을 입력하세요 (빈 줄로 종료)\n")

    while True:
        try:
            url = input("url> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not url:
            break
        char_proba = char_bundle.predict_proba([url]).reindex(
            columns=classes).iloc[0]
        second_proba = second_bundle.predict_proba([url]).reindex(
            columns=classes).iloc[0]
        blended = (args.char_weight * char_proba
                   + (1 - args.char_weight) * second_proba)
        label = blended.idxmax()
        detail = "  ".join(f"{c} {p:.1%}" for c, p in blended.items())
        each = (f"char {char_proba.idxmax()} {char_proba.max():.0%} / "
                f"second {second_proba.idxmax()} {second_proba.max():.0%}")
        print(f"  → {label}  ({detail})  [{each}]\n")


if __name__ == "__main__":
    main()
