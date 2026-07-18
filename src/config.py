"""Application and operational policy configuration."""

OPENAI_TIMEOUT_SECONDS = 60.0
OPENAI_MAX_RETRIES = 2

RISK_MEDIUM_THRESHOLD = 0.4
RISK_HIGH_THRESHOLD = 0.7

MAX_SMS_CHARS = 10_000
MAX_EML_SIZE_BYTES = 25 * 1024 * 1024
MAX_URL_CANDIDATES = 100
MAX_URL_LENGTH_CHARS = 2_048
MAX_URLS_TO_ANALYZE = 20
MAX_ANALYSIS_REQUEST_BYTES = 1024 * 1024

SUSPICIOUS_PREVIOUS_EXTENSIONS = {
    ".pdf",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".exe",
    ".class",
    ".py",
    ".js",
}

KNOWN_BINARY_SIGNATURES = (
    (b"%PDF", "PDF"),
    (b"PK\x03\x04", "ZIP"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"\xca\xfe\xba\xbe", "Java class"),
    (b"MZ", "Windows executable"),
)
