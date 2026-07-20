from pathlib import Path

import joblib
import pytest


@pytest.mark.parametrize(
    "model_path",
    [Path("models/email_spam_model.pkl"), Path("models/sms_spam_model.pkl")],
)
def test_message_model_artifact_loads_and_predicts(model_path: Path) -> None:
    model = joblib.load(model_path)
    probabilities = model.predict_proba(["테스트 메시지"])[0]

    assert len(probabilities) == 2
    assert all(0.0 <= float(value) <= 1.0 for value in probabilities)
    assert sum(float(value) for value in probabilities) == pytest.approx(1.0)
