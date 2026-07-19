import subprocess
import sys


def test_default_url_cli_falls_back_to_included_char_model() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/predict_url_cli.py"],
        input="\n",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "단일 모델 로딩 완료" in completed.stdout
    assert "앙상블을 생략합니다" in completed.stdout
