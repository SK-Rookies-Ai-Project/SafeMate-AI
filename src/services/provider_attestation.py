"""Offline, crash-safe publication and verification of provider attestations."""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
import time
import unicodedata
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

RECEIPT_SCHEMA = "safemate.provider_probe_receipt.v1"
ATTESTATION_SCHEMA = "safemate.provider_contract_attestation.v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVIEWER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{1,127}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_APPROVED_FILES = 200
_VECTOR_BATCH_POLL_LIMIT = 8
_RECEIPT_CEILINGS = {
    "max_retries": 0,
    "responses": 4,
    "vector_operations": 1 + _MAX_APPROVED_FILES + 1 + _VECTOR_BATCH_POLL_LIMIT + 2,
    "max_output_tokens": 512,
    "max_tool_calls": 5,
}
_RECEIPT_CHECKS = {"function", "web", "file", "store"}
_RECEIPT_COUNTS = {"approved_files", "completed_files", "response_attempts"}
_RECEIPT_STATES = {"file_search", "function_replay", "upload", "web_search"}


class AttestationError(RuntimeError):
    """A fail-closed provider attestation error with a safe machine code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _reject_noncanonical(value: Any) -> None:
    if isinstance(value, float):
        raise AttestationError("canonical_float")
    if isinstance(value, str) and unicodedata.normalize("NFC", value) != value:
        raise AttestationError("canonical_unicode")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AttestationError("canonical_key")
            _reject_noncanonical(key)
            _reject_noncanonical(item)
    elif isinstance(value, list):
        for item in value:
            _reject_noncanonical(item)
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise AttestationError("canonical_value")


def canonical_json_bytes(value: Any) -> bytes:
    """Return strict compact UTF-8 JSON. Arrays retain their supplied ordering."""
    _reject_noncanonical(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AttestationError("canonical_json") from error


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise AttestationError("canonical_duplicate_key")
        output[key] = value
    return output


def parse_canonical_json(content: bytes) -> Any:
    if content.startswith(b"\xef\xbb\xbf") or content.endswith(b"\n"):
        raise AttestationError("noncanonical_json")
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_float=lambda _: (_ for _ in ()).throw(AttestationError("canonical_float")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AttestationError("canonical_json") from error
    _reject_noncanonical(value)
    if canonical_json_bytes(value) != content:
        raise AttestationError("noncanonical_json")
    return value


def _timestamp(value: Any) -> None:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise AttestationError("invalid_timestamp")
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise AttestationError("invalid_timestamp") from error


def _digest(value: Any, code: str = "invalid_digest") -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise AttestationError(code)


def _closed_object(value: Any, required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise AttestationError("invalid_schema")
    return value


def validate_receipt(value: Any) -> dict[str, Any]:
    receipt = _closed_object(value, {"schema", "sdk_version", "model", "probed_at", "ceilings", "checks", "counts", "states", "vector_attestation_digest", "corpus_manifest_digest"})
    if receipt["schema"] != RECEIPT_SCHEMA:
        raise AttestationError("invalid_schema")
    for field in ("sdk_version", "model"):
        if not isinstance(receipt[field], str) or not receipt[field]:
            raise AttestationError("invalid_schema")
    _timestamp(receipt["probed_at"])
    ceilings = receipt["ceilings"]
    if (
        not isinstance(ceilings, dict)
        or set(ceilings) != set(_RECEIPT_CEILINGS)
        or any(type(ceilings[key]) is not int for key in _RECEIPT_CEILINGS)
        or ceilings != _RECEIPT_CEILINGS
    ):
        raise AttestationError("invalid_schema")
    if (
        not isinstance(receipt["checks"], dict)
        or set(receipt["checks"]) != _RECEIPT_CHECKS
        or any(item is not True for item in receipt["checks"].values())
    ):
        raise AttestationError("invalid_schema")
    counts = receipt["counts"]
    if (
        not isinstance(counts, dict)
        or set(counts) != _RECEIPT_COUNTS
        or any(not isinstance(item, int) or isinstance(item, bool) for item in counts.values())
        or not 1 <= counts["approved_files"] <= _MAX_APPROVED_FILES
        or counts["completed_files"] != counts["approved_files"]
        or counts["response_attempts"] != _RECEIPT_CEILINGS["responses"]
    ):
        raise AttestationError("invalid_schema")
    if (
        not isinstance(receipt["states"], dict)
        or set(receipt["states"]) != _RECEIPT_STATES
        or any(item != "completed" for item in receipt["states"].values())
    ):
        raise AttestationError("invalid_schema")
    _digest(receipt["vector_attestation_digest"])
    _digest(receipt["corpus_manifest_digest"])
    return receipt


def validate_attestation(value: Any) -> dict[str, Any]:
    attestation = _closed_object(value, {"schema", "sdk_version", "model", "issued_at", "expires_at", "checks", "probe_receipt_digest", "reviewer_id"})
    if attestation["schema"] != ATTESTATION_SCHEMA:
        raise AttestationError("invalid_schema")
    for field in ("sdk_version", "model"):
        if not isinstance(attestation[field], str) or not attestation[field]:
            raise AttestationError("invalid_schema")
    _timestamp(attestation["issued_at"])
    _timestamp(attestation["expires_at"])
    if (
        not isinstance(attestation["checks"], dict)
        or set(attestation["checks"]) != _RECEIPT_CHECKS
        or any(item is not True for item in attestation["checks"].values())
    ):
        raise AttestationError("invalid_schema")
    _digest(attestation["probe_receipt_digest"])
    if not isinstance(attestation["reviewer_id"], str) or not _REVIEWER.fullmatch(attestation["reviewer_id"]):
        raise AttestationError("invalid_reviewer")
    _attestation_window(attestation)
    return attestation
def _attestation_window(attestation: Mapping[str, Any]) -> tuple[dt.datetime, dt.datetime]:
    issued = dt.datetime.strptime(attestation["issued_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    expires = dt.datetime.strptime(attestation["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    if expires <= issued or expires - issued > dt.timedelta(days=30):
        raise AttestationError("invalid_attestation_window")
    return issued, expires


def _validate_pair(attestation: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    _attestation_window(attestation)
    for field in ("sdk_version", "model", "checks"):
        if attestation[field] != receipt[field]:
            raise AttestationError("attestation_receipt_mismatch")
    probed_at = dt.datetime.strptime(receipt["probed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    issued, expires = _attestation_window(attestation)
    if not issued <= probed_at < expires:
        raise AttestationError("attestation_receipt_mismatch")


def _regular(path: Path, missing_code: str) -> None:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError as error:
        raise AttestationError(missing_code) from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise AttestationError("nonregular_file")


def _read_verified_receipt(path: Path, expected_digest: str) -> dict[str, Any]:
    _regular(path, "receipt_missing")
    content = path.read_bytes()
    if sha256_hex(content) != expected_digest:
        raise AttestationError("receipt_digest_mismatch")
    receipt = validate_receipt(parse_canonical_json(content))
    return receipt


def _read_verified_attestation(path: Path, expected_digest: str | None = None) -> tuple[dict[str, Any], bytes]:
    _regular(path, "attestation_missing")
    content = path.read_bytes()
    if expected_digest is not None and not hmac.compare_digest(sha256_hex(content), expected_digest):
        raise AttestationError("attestation_digest_mismatch")
    return validate_attestation(parse_canonical_json(content)), content


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _temp_file(directory: Path, prefix: str) -> tuple[int, Path]:
    descriptor, name = tempfile.mkstemp(prefix=prefix, dir=directory)
    return descriptor, Path(name)


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]


class AttestationPublisher:
    """Publishes immutable receipts before replacing the active pointer last."""

    def __init__(self, active_path: Path | str, *, failure_injector: Callable[[str], None] | None = None, lock_timeout: float = 5.0) -> None:
        self.active_path = Path(active_path)
        self.receipts_path = Path(f"{self.active_path}.receipts")
        self.lock_path = Path(f"{self.active_path}.lock")
        self.failure_injector = failure_injector
        self.lock_timeout = lock_timeout

    def _checkpoint(self, name: str) -> None:
        if self.failure_injector is not None:
            self.failure_injector(name)

    def _validate_paths(self) -> None:
        parent = self.active_path.parent
        if not parent.is_dir() or parent.is_symlink():
            raise AttestationError("invalid_attestation_directory")
        if self.receipts_path.exists() or self.receipts_path.is_symlink():
            if self.receipts_path.is_symlink() or not self.receipts_path.is_dir():
                raise AttestationError("invalid_receipt_directory")
            if os.stat(self.receipts_path).st_dev != os.stat(parent).st_dev:
                raise AttestationError("cross_filesystem")
        if self.lock_path.exists():
            _regular(self.lock_path, "lock_missing")
        if self.active_path.exists() or self.active_path.is_symlink():
            _regular(self.active_path, "attestation_missing")

    @contextmanager
    def _lock(self) -> Any:
        descriptor = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            os.chmod(self.lock_path, 0o600)
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise AttestationError("writer_locked")
                    time.sleep(0.05)
            yield
        finally:
            os.close(descriptor)

    def _prepare(self, receipt: Mapping[str, Any], reviewer_id: str, issued_at: str, expires_at: str) -> tuple[bytes, str, bytes, str]:
        receipt_value = dict(receipt)
        validate_receipt(receipt_value)
        receipt_bytes = canonical_json_bytes(receipt_value)
        receipt_digest = sha256_hex(receipt_bytes)
        if not isinstance(reviewer_id, str) or not _REVIEWER.fullmatch(reviewer_id):
            raise AttestationError("invalid_reviewer")
        attestation_value = {
            "schema": ATTESTATION_SCHEMA,
            "sdk_version": receipt_value["sdk_version"],
            "model": receipt_value["model"],
            "issued_at": issued_at,
            "expires_at": expires_at,
            "checks": receipt_value["checks"],
            "probe_receipt_digest": receipt_digest,
            "reviewer_id": reviewer_id,
        }
        validate_attestation(attestation_value)
        _validate_pair(attestation_value, receipt_value)
        attestation_bytes = canonical_json_bytes(attestation_value)
        return receipt_bytes, receipt_digest, attestation_bytes, sha256_hex(attestation_bytes)

    def _publish_locked(self, receipt: Mapping[str, Any], *, reviewer_id: str, issued_at: str, expires_at: str) -> dict[str, str]:
        receipt_bytes, receipt_digest, attestation_bytes, attestation_digest = self._prepare(
            receipt, reviewer_id, issued_at, expires_at
        )
        receipts_preexisting = self.receipts_path.exists()
        self.receipts_path.mkdir(mode=0o700, exist_ok=True)
        if not receipts_preexisting:
            self._checkpoint("receipt_directory_created")
            _fsync_directory(self.active_path.parent)
            self._checkpoint("receipt_parent_directory_fsynced")
        if self.receipts_path.is_symlink() or not self.receipts_path.is_dir():
            raise AttestationError("invalid_receipt_directory")
        if os.stat(self.receipts_path).st_dev != os.stat(self.active_path.parent).st_dev:
            raise AttestationError("cross_filesystem")
        receipt_temp: Path | None = None
        attestation_temp: Path | None = None
        try:
            descriptor, receipt_temp = _temp_file(self.receipts_path, ".receipt-")
            os.chmod(receipt_temp, 0o600)
            self._checkpoint("receipt_temp_created")
            try:
                _write_all(descriptor, receipt_bytes)
                self._checkpoint("receipt_written")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._checkpoint("receipt_file_fsynced")
            final_receipt = self.receipts_path / f"{receipt_digest}.json"
            try:
                os.link(receipt_temp, final_receipt)
                receipt_temp.unlink()
                receipt_temp = None
                _fsync_directory(self.receipts_path)
            except FileExistsError:
                pass
            self._checkpoint("receipt_committed")
            verified_receipt = _read_verified_receipt(final_receipt, receipt_digest)
            if canonical_json_bytes(verified_receipt) != receipt_bytes:
                raise AttestationError("receipt_digest_collision")
            self._checkpoint("receipt_verified")

            descriptor, attestation_temp = _temp_file(self.active_path.parent, ".attestation-")
            os.chmod(attestation_temp, 0o600)
            self._checkpoint("attestation_temp_created")
            try:
                _write_all(descriptor, attestation_bytes)
                self._checkpoint("attestation_written")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._checkpoint("attestation_file_fsynced")
            parsed, temp_bytes = _read_verified_attestation(attestation_temp)
            _validate_pair(parsed, verified_receipt)
            if temp_bytes != attestation_bytes or parsed["probe_receipt_digest"] != receipt_digest or sha256_hex(temp_bytes) != attestation_digest:
                raise AttestationError("attestation_temp_verification_failed")
            self._checkpoint("attestation_verified")
            self._checkpoint("before_pointer_replace")
            os.replace(attestation_temp, self.active_path)
            attestation_temp = None
            self._checkpoint("after_pointer_replace")
            _fsync_directory(self.active_path.parent)
            self._checkpoint("pointer_directory_fsynced")
            active, active_bytes = _read_verified_attestation(self.active_path)
            _validate_pair(active, _read_verified_receipt(final_receipt, receipt_digest))
            if active_bytes != attestation_bytes or active["probe_receipt_digest"] != receipt_digest:
                raise AttestationError("active_verification_failed")
            self._checkpoint("post_commit_verified")
            return {"attestation_digest": attestation_digest, "receipt_digest": receipt_digest}
        finally:
            for temporary in (receipt_temp, attestation_temp):
                if temporary is not None:
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass

    def publish(self, receipt: Mapping[str, Any], *, reviewer_id: str, issued_at: str, expires_at: str) -> dict[str, str]:
        """Commit a prebuilt offline receipt under the sole writer lock."""
        self._validate_paths()
        with self._lock():
            self._checkpoint("lock_acquired")
            return self._publish_locked(receipt, reviewer_id=reviewer_id, issued_at=issued_at, expires_at=expires_at)

    def publish_transaction(self, probe: Callable[[], Mapping[str, Any]], *, reviewer_id: str, issued_at: str, expires_at: str) -> dict[str, str]:
        """Run a bounded injected probe and publish its receipt in one lock transaction."""
        if not callable(probe):
            raise AttestationError("invalid_probe")
        self._validate_paths()
        with self._lock():
            self._checkpoint("lock_acquired")
            self._checkpoint("before_probe")
            receipt = probe()
            self._checkpoint("after_probe")
            if not isinstance(receipt, Mapping):
                raise AttestationError("invalid_probe_receipt")
            return self._publish_locked(receipt, reviewer_id=reviewer_id, issued_at=issued_at, expires_at=expires_at)

    def collect_orphan_receipts(self, *, older_than_days: int = 30) -> list[str]:
        """Return collectable receipt digests without deleting any artifact."""
        if not isinstance(older_than_days, int) or older_than_days < 0:
            raise AttestationError("invalid_retention")
        self._validate_paths()
        if not self.receipts_path.exists():
            return []
        active, _ = _read_verified_attestation(self.active_path)
        active_digest = active["probe_receipt_digest"]
        cutoff = time.time() - older_than_days * 86400
        orphans: list[str] = []
        for candidate in self.receipts_path.iterdir():
            if candidate.is_symlink():
                raise AttestationError("nonregular_file")
            if not candidate.is_file():
                raise AttestationError("nonregular_file")
            name = candidate.name
            if not name.endswith(".json") or not _DIGEST.fullmatch(name[:-5]):
                raise AttestationError("invalid_receipt_filename")
            if name[:-5] != active_digest and candidate.stat().st_mtime <= cutoff:
                orphans.append(name[:-5])
        return sorted(orphans)

def health(active_path: Path | str, protected_digest: str, *, now: dt.datetime | None = None, expected_sdk_version: str | None = None, expected_model: str | None = None) -> dict[str, str]:
    """Verify local trust artifacts only; this function never probes a provider or writes."""
    _digest(protected_digest, "invalid_protected_digest")
    path = Path(active_path)
    attestation, content = _read_verified_attestation(path, protected_digest)
    if expected_sdk_version is not None and attestation["sdk_version"] != expected_sdk_version:
        raise AttestationError("sdk_version_mismatch")
    if expected_model is not None and attestation["model"] != expected_model:
        raise AttestationError("model_mismatch")
    current = now if now is not None else dt.datetime.now(dt.timezone.utc)
    if not isinstance(current, dt.datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise AttestationError("invalid_current_time")
    current = current.astimezone(dt.timezone.utc)
    issued, expires = _attestation_window(attestation)
    if current < issued:
        raise AttestationError("attestation_not_issued")
    if current >= expires:
        raise AttestationError("attestation_expired")
    receipt_path = Path(f"{path}.receipts") / f"{attestation['probe_receipt_digest']}.json"
    receipt = _read_verified_receipt(receipt_path, attestation["probe_receipt_digest"])
    _validate_pair(attestation, receipt)
    probed_at = dt.datetime.strptime(receipt["probed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    if probed_at > current:
        raise AttestationError("probe_not_completed")
    return {
        "status": "ready",
        "attestation_digest": sha256_hex(content),
        "receipt_digest": attestation["probe_receipt_digest"],
        "vector_attestation_digest": receipt["vector_attestation_digest"],
    }
