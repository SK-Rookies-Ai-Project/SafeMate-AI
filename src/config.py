"""Application and operational policy configuration."""
import os

FOLLOWUP_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})


def is_openai_followup_enabled(value: str | None = None) -> bool:
    """Return whether the explicitly opt-in follow-up capability is enabled."""
    if value is None:
        value = os.getenv("SAFEMATE_OPENAI_FOLLOWUP_ENABLED")
    return isinstance(value, str) and value.casefold() in FOLLOWUP_ENABLED_VALUES


def is_openai_followup_configured() -> bool:
    """Return whether provider credentials and trust anchors are configured."""
    return all(
        os.getenv(name, "").strip()
        for name in (
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH",
            "OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256",
        )
    )


def is_openai_followup_available() -> bool:
    """Return whether follow-up is explicitly enabled and safely constructible."""
    return is_openai_followup_enabled() and is_openai_followup_configured()

OPENAI_TIMEOUT_SECONDS = 20.0
OPENAI_FOLLOWUP_TURN_TIMEOUT_SECONDS = 45.0
OPENAI_FOLLOWUP_READINESS_TIMEOUT_SECONDS = 5.0
OPENAI_MAX_RETRIES = 0

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
