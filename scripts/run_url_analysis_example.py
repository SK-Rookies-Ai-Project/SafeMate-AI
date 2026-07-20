"""Run one URL through the SafeMate URL analyzer."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analyzers.url_analyzer import analyze_url


if __name__ == "__main__":
    url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://example.com/login"
    )
    print(json.dumps(analyze_url(url), ensure_ascii=False, indent=2))
