"""URL 분석 모듈 공용 상수: 데이터 경로, 라벨, 민감 키워드."""

from pathlib import Path

# ---------------------------------------------------------------------------
# 데이터/모델 경로
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = PROJECT_ROOT / "models"
URL_REPUTATION_DB = MODELS_DIR / "url_reputation.sqlite3"

DATA_DIR = PROJECT_ROOT / "data" / "raw"
ALL_CSV = DATA_DIR / "All.csv"                      # ISCX-URL-2016 feature 데이터
URL_BINARY_CSV = DATA_DIR / "url_binary_dataset.csv"  # raw URL + 악성/정상

# ---------------------------------------------------------------------------
# 라벨
# ---------------------------------------------------------------------------
LABEL_COLUMN = "URL_Type_obf_Type"

# 정상으로 취급하는 라벨 (그 외는 전부 위험)
BENIGN_LABELS = frozenset({"benign", "Benign", "정상"})

RISK_VERDICT = "위험"
SAFE_VERDICT = "안전"

# ---------------------------------------------------------------------------
# feature 추출용 상수
# ---------------------------------------------------------------------------

# 피싱 URL에 자주 등장하는 민감 단어 (URL_sensitiveWord)
SENSITIVE_WORDS = (
    "secure", "account", "webscr", "login", "signin", "banking", "confirm",
    "ebayisapi", "paypal", "password", "verify", "update", "free", "bonus",
)

# 실행 파일로 취급하는 확장자 (executable)
EXECUTABLE_EXTENSIONS = (
    "exe", "bat", "cmd", "com", "msi", "scr", "dll", "ps1", "vbs",
    "jar", "apk", "sh", "bin",
)

# delimeter_* feature에서 세는 구분자 집합
DELIMITERS = frozenset(".-_/?=&:;,@#%~+")

VOWELS = frozenset("aeiouAEIOU")
