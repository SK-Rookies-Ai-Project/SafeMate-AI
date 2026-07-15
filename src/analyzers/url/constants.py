"""URL 분석 모듈 공용 상수: 데이터 경로, 라벨, 민감 키워드."""

from pathlib import Path

# ---------------------------------------------------------------------------
# 데이터/모델 경로
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = PROJECT_ROOT / "models"

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
    "secure",
    "account",
    "webscr",
    "login",
    "signin",
    "banking",
    "confirm",
    "ebayisapi",
    "paypal",
    "password",
    "verify",
    "update",
    "free",
    "bonus",

    "krakentxy",
    "1qw2es2z",
    "qwo231sdx",
    "wusps",
    "skyudrive",
    "onlineapphost",
    "1eaba4fdae",
    "qweqwi",
    "agaratas",
    "hostlogininfopos",
    "hgvllc",
    "taxationofficeato",
    "winbank_update_browser",
    "pub?start=false&amp;loop=false&amp;delayms=3000",
    "refundonex",
    "tmpftp",
    "xyz:808",
    "linkedinaut",
    "ha004",
    "cpl64",
    "data_get_params",
    "05fe317c",
    "930d369db441",
    "buydevelopquiet",
    "pochtarefund",
    "228:8070",
    "pdfdocdownloadspanel",
    "noconnection",
    "baalejibreel",
    "53244ds",
    "piperoert22",
    "luisorlandini",
    "tamparealu",
    "3d80df5d12cdfe6450a782fc87bf66b444",
    "rheiwj",
    "commbankaustralia",
    "xerrrload04",
    "loaadkkkk14",
    "stickamcomlogindo",
    "loadlisboa",
    "launch_error",
    "launch_info",
    "erytho",
    "dl_ff",
    "solidstreamer",
    "%3d",
    "php?cmd=_login",
    "fmicode",
    "'9d345009",
    "westuatrans",
)

# 실행 파일로 취급하는 확장자 (executable)
EXECUTABLE_EXTENSIONS = (
    "exe", "bat", "cmd", "com", "msi", "scr", "dll", "ps1", "vbs",
    "jar", "apk", "sh", "bin",
)

# delimeter_* feature에서 세는 구분자 집합
DELIMITERS = frozenset(".-_/?=&:;,@#%~+")

VOWELS = frozenset("aeiouAEIOU")
