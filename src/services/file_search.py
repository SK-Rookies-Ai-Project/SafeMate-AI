"""OpenAI hosted File Search configuration and strict evidence admission."""

from __future__ import annotations

import datetime as dt
import json
import hashlib
import hmac
import os
import re
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from src.services.provider_attestation import AttestationError, health as provider_health

FILE_SEARCH_INCLUDE = "file_search_call.results"
MAX_RESPONSE_OUTPUT_ITEMS = 16
MAX_RESPONSE_CONTENT_PARTS = 8
MAX_RESPONSE_ANNOTATIONS = 32
MAX_FILE_RESULTS_PER_CALL = 50
VECTOR_LIST_PAGE_SIZE = 100
VECTOR_MAX_LIST_PAGES = 2
VECTOR_READY_TTL_SECONDS = 60.0
VECTOR_UNREADY_TTL_SECONDS = 15.0
VECTOR_INVENTORY_SCHEMA = "safemate.vector_inventory_attestation.v1"
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def build_attested_file_inventory_provider(
    client: Any,
    *,
    vector_store_id: str,
    model: str,
    sdk_version: str,
    provider_attestation_digest: str,
    attestation_path: str | None = None,
    protected_digest: str | None = None,
    provider_attestation_path: str | None = None,
    now: Callable[[], dt.datetime] | None = None,
) -> Callable[[], Mapping[str, Any]]:
    """Load a deployment attestation offline, then return a lazy readiness callable.

    Invalid deployment input returns an inert callable rather than retaining
    enough state to reach the Vector API.
    """
    inventory = _load_vector_inventory_attestation(
        vector_store_id=vector_store_id,
        model=model,
        sdk_version=sdk_version,
        provider_attestation_digest=provider_attestation_digest,
        attestation_path=attestation_path,
        protected_digest=protected_digest,
        provider_attestation_path=provider_attestation_path,
        now=now,
    )
    if inventory is None:
        return _default_unready_inventory
    expected_inventory, vector_digest, corpus_version, expires_at = inventory
    wall_clock = now or (lambda: dt.datetime.now(dt.timezone.utc))
    readiness = build_file_inventory_provider(
        client,
        vector_store_id=vector_store_id,
        expected_inventory=expected_inventory,
        vector_attestation_digest=vector_digest,
        provider_attestation_digest=provider_attestation_digest,
        model=model,
        sdk_version=sdk_version,
        corpus_version=corpus_version,
        attestation_expires_at=expires_at,
        wall_clock=wall_clock,
    )

    def attested_readiness(
        deadline_seconds: float | None = None,
        remaining_seconds: Callable[[], float] | None = None,
    ) -> Mapping[str, Any]:
        try:
            current = wall_clock()
            if current.tzinfo is None or current.astimezone(dt.timezone.utc) >= expires_at:
                return _unready_inventory()
        except Exception:
            return _unready_inventory()
        return readiness(
            deadline_seconds=deadline_seconds,
            remaining_seconds=remaining_seconds,
        )

    attested_readiness._safemate_deadline_aware = True
    return attested_readiness


def _load_vector_inventory_attestation(
    *,
    vector_store_id: str,
    model: str,
    sdk_version: str,
    provider_attestation_digest: str,
    attestation_path: str | None,
    protected_digest: str | None,
    provider_attestation_path: str | None,
    now: Callable[[], dt.datetime] | None,
) -> tuple[dict[str, Any], str, str, dt.datetime] | None:
    path = (attestation_path if attestation_path is not None else os.getenv("OPENAI_VECTOR_INVENTORY_ATTESTATION_PATH", "")).strip()
    digest = (protected_digest if protected_digest is not None else os.getenv("OPENAI_VECTOR_INVENTORY_ATTESTATION_SHA256", "")).strip()
    provider_path = (
        provider_attestation_path
        if provider_attestation_path is not None
        else os.getenv("OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH", "")
    ).strip()
    if not path or not provider_path or not _safe_digest(digest) or not _safe_digest(provider_attestation_digest):
        return None
    try:
        target = Path(path)
        if target.is_symlink() or not target.is_file():
            return None
        content = target.read_bytes()
        actual_digest = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(actual_digest, digest):
            return None
        value = _parse_canonical_json(content)
        wall_clock = now or (lambda: dt.datetime.now(dt.timezone.utc))
        current = wall_clock()
        authoritative_vector_digest = provider_health(
            provider_path,
            provider_attestation_digest,
            now=current,
            expected_sdk_version=sdk_version,
            expected_model=model,
        )["vector_attestation_digest"]
        if not hmac.compare_digest(authoritative_vector_digest, digest):
            return None
        return _validate_vector_inventory_attestation(
            value,
            vector_store_id=vector_store_id,
            model=model,
            sdk_version=sdk_version,
            provider_attestation_digest=provider_attestation_digest,
            vector_attestation_digest=digest,
            now=current,
        )
    except (AttestationError, AttributeError, OSError, TypeError, ValueError, UnicodeError):
        return None


def _parse_canonical_json(content: bytes) -> Any:
    if content.startswith(b"\xef\xbb\xbf") or content.endswith(b"\n"):
        raise ValueError("noncanonical_json")

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    value = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=no_duplicates,
        parse_float=lambda _: (_ for _ in ()).throw(ValueError("float")),
    )
    if _canonical_json_bytes(value) != content:
        raise ValueError("noncanonical_json")
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    def validate(item: Any) -> None:
        if isinstance(item, float) or not isinstance(item, (dict, list, str, int, bool, type(None))):
            raise ValueError("invalid_value")
        if isinstance(item, str) and unicodedata.normalize("NFC", item) != item:
            raise ValueError("non_nfc")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("invalid_key")
                validate(key)
                validate(child)
        elif isinstance(item, list):
            for child in item:
                validate(child)

    validate(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate_vector_inventory_attestation(
    value: Any,
    *,
    vector_store_id: str,
    model: str,
    sdk_version: str,
    provider_attestation_digest: str,
    vector_attestation_digest: str,
    now: dt.datetime,
) -> tuple[dict[str, Any], str, str, dt.datetime] | None:
    required = {
        "schema", "sdk_version", "model", "vector_store_id", "corpus_version",
        "issued_at", "expires_at", "corpus_manifest_digest", "completed_file_count", "files",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("schema") != VECTOR_INVENTORY_SCHEMA:
        return None
    if (
        not all(_safe_text_identifier(item) for item in (value["sdk_version"], value["model"]))
        or not _safe_provider_id(value["vector_store_id"])
        or value["sdk_version"] != sdk_version
        or value["model"] != model
        or value["vector_store_id"] != vector_store_id
    ):
        return None
    corpus_version = value["corpus_version"]
    if (
        not isinstance(corpus_version, str)
        or not corpus_version
        or unicodedata.normalize("NFC", corpus_version) != corpus_version
        or not _safe_digest(value["corpus_manifest_digest"])
    ):
        return None
    issued = _parse_timestamp(value["issued_at"])
    expires = _parse_timestamp(value["expires_at"])
    if issued is None or expires is None or expires <= issued or expires - issued > dt.timedelta(days=30):
        return None
    if not isinstance(now, dt.datetime) or now.tzinfo is None or now.utcoffset() is None:
        return None
    now = now.astimezone(dt.timezone.utc)
    if not issued <= now < expires:
        return None
    if not isinstance(value["files"], list) or len(value["files"]) > 200 or not all(
        isinstance(row, dict)
        and set(row) == {"file_id", "filename", "sha256"}
        and _safe_provider_id(row["file_id"])
        for row in value["files"]
    ):
        return None
    expected = _expected_inventory(value)
    if expected is None:
        return None
    return (value, vector_attestation_digest, corpus_version, expires)


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not _TIMESTAMP_PATTERN.fullmatch(value):
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _default_unready_inventory() -> Mapping[str, Any]:
    return _unready_inventory()

class VectorReadinessService:
    """Lazily verify a bounded Vector Store inventory for the File Search seam.

    The callable deliberately exposes only attested filenames and safe digests;
    provider store and file identifiers remain inside this object.
    """
    _safemate_deadline_aware = True

    def __init__(
        self,
        client: Any,
        *,
        vector_store_id: str,
        expected_inventory: Mapping[str, Any],
        vector_attestation_digest: str,
        provider_attestation_digest: str,
        model: str,
        sdk_version: str,
        corpus_version: str,
        clock: Callable[[], float] = time.monotonic,
        deadline_seconds: float = 5.0,
        attestation_expires_at: dt.datetime | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        if not isinstance(deadline_seconds, (int, float)) or isinstance(deadline_seconds, bool) or not 0 < deadline_seconds <= 5:
            raise ValueError("deadline_seconds must be between zero and five seconds")
        self._client = client
        self._vector_store_id = vector_store_id
        self._expected_inventory = expected_inventory
        self._vector_attestation_digest = vector_attestation_digest
        self._provider_attestation_digest = provider_attestation_digest
        self._model = model
        self._sdk_version = sdk_version
        self._corpus_version = corpus_version
        self._clock = clock
        self._deadline_seconds = float(deadline_seconds)
        self._attestation_expires_at = attestation_expires_at
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
        self._flights: dict[tuple[str, ...], threading.Event] = {}
        self._lock = threading.Lock()
        self._active_key: tuple[str, ...] | None = None

    def __call__(
        self,
        deadline_seconds: float | None = None,
        remaining_seconds: Callable[[], float] | None = None,
    ) -> Mapping[str, Any]:
        """Return a fresh, privacy-safe readiness inventory without eager I/O."""
        if (
            deadline_seconds is not None
            and (
                not isinstance(deadline_seconds, (int, float))
                or isinstance(deadline_seconds, bool)
                or deadline_seconds <= 0
            )
        ):
            return _unready_inventory()
        if remaining_seconds is not None and not callable(remaining_seconds):
            return _unready_inventory()
        try:
            started = self._clock()
        except Exception:
            return _unready_inventory()
        budget = self._deadline_seconds if deadline_seconds is None else min(self._deadline_seconds, float(deadline_seconds))
        local_deadline = started + budget
        if self._remaining_budget(local_deadline, remaining_seconds) <= 0:
            return _unready_inventory()
        key = self._cache_key()
        if key is None:
            return _unready_inventory()
        with self._lock:
            if self._active_key != key:
                self._cache.clear()
                self._active_key = key
            cached = self._cached_inventory(key)
            if cached is not None:
                return cached
            flight = self._flights.get(key)
            if flight is None:
                flight = threading.Event()
                self._flights[key] = flight
                leader = True
            else:
                leader = False
        if not leader:
            timeout = self._remaining_budget(local_deadline, remaining_seconds)
            if timeout <= 0 or not flight.wait(timeout=timeout):
                return _unready_inventory()
            if self._remaining_budget(local_deadline, remaining_seconds) <= 0:
                return _unready_inventory()
            with self._lock:
                cached = self._cached_inventory(key)
            return cached if cached is not None else _unready_inventory()
        inventory = _unready_inventory()
        try:
            inventory = self._refresh(local_deadline, remaining_seconds)
        except Exception:
            pass
        finally:
            if inventory.get("ready") is True and self._remaining_budget(local_deadline, remaining_seconds) <= 0:
                inventory = _unready_inventory()
            try:
                ttl = VECTOR_READY_TTL_SECONDS if inventory.get("ready") is True else VECTOR_UNREADY_TTL_SECONDS
                expires_at = self._clock() + min(ttl, self._attestation_remaining())
            except Exception:
                inventory = _unready_inventory()
                expires_at = float("inf")
            with self._lock:
                self._cache[key] = (expires_at, _copy_inventory(inventory))
                self._flights.pop(key).set()
        return _copy_inventory(inventory)

    def _cached_inventory(self, key: tuple[str, ...]) -> dict[str, Any] | None:
        try:
            cached = self._cache.get(key)
            if cached is not None and self._clock() < cached[0] and self._attestation_remaining() > 0:
                return _copy_inventory(cached[1])
        except Exception:
            return None
        return None

    def _attestation_remaining(self) -> float:
        if self._attestation_expires_at is None:
            return float("inf")
        try:
            current = self._wall_clock()
            if current.tzinfo is None:
                return 0.0
            return (self._attestation_expires_at - current.astimezone(dt.timezone.utc)).total_seconds()
        except Exception:
            return 0.0

    def _remaining_budget(
        self,
        local_deadline: float,
        remaining_seconds: Callable[[], float] | None,
    ) -> float:
        try:
            remaining = local_deadline - self._clock()
            if remaining_seconds is not None:
                shared_remaining = remaining_seconds()
                if (
                    not isinstance(shared_remaining, (int, float))
                    or isinstance(shared_remaining, bool)
                ):
                    return 0.0
                remaining = min(remaining, float(shared_remaining))
            return min(remaining, self._attestation_remaining())
        except Exception:
            return 0.0

    def _cache_key(self) -> tuple[str, ...] | None:
        values = (
            self._vector_store_id,
            self._vector_attestation_digest,
            self._provider_attestation_digest,
            self._model,
            self._sdk_version,
            self._corpus_version,
        )
        if not all(_safe_text_identifier(value) for value in (self._model, self._sdk_version, self._corpus_version)):
            return None
        if not _safe_provider_id(self._vector_store_id):
            return None
        if not _safe_digest(self._vector_attestation_digest) or not _safe_digest(self._provider_attestation_digest):
            return None
        return values

    def _refresh(
        self,
        local_deadline: float,
        remaining_seconds: Callable[[], float] | None = None,
    ) -> dict[str, Any]:
        expected = _expected_inventory(self._expected_inventory)
        if expected is None:
            return _unready_inventory()
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        remote_ids: set[str] = set()
        cursor: str | None = None
        for page_number in range(VECTOR_MAX_LIST_PAGES):
            request_timeout = self._remaining_budget(local_deadline, remaining_seconds)
            if request_timeout <= 0:
                return _unready_inventory()
            page = self._list_page(cursor, timeout=request_timeout)
            if self._remaining_budget(local_deadline, remaining_seconds) <= 0:
                return _unready_inventory()
            rows = _get_value(page, "data")
            has_more = _get_value(page, "has_more")
            last_id = _get_value(page, "last_id")
            if not isinstance(rows, list) or len(rows) > VECTOR_LIST_PAGE_SIZE or not isinstance(has_more, bool):
                return _unready_inventory()
            if cursor is not None and cursor in seen_cursors:
                return _unready_inventory()
            if cursor is not None:
                seen_cursors.add(cursor)
            for row in rows:
                identifier = _get_value(row, "file_id", _get_value(row, "id"))
                if not _safe_provider_id(identifier) or identifier in seen_ids:
                    return _unready_inventory()
                if _get_value(row, "status") != "completed":
                    return _unready_inventory()
                seen_ids.add(identifier)
                remote_ids.add(identifier)
            if not has_more:
                if remote_ids != set(expected) or self._remaining_budget(local_deadline, remaining_seconds) <= 0:
                    return _unready_inventory()
                return _ready_inventory(expected, self._vector_attestation_digest, self._provider_attestation_digest, self._corpus_version)
            if page_number + 1 >= VECTOR_MAX_LIST_PAGES:
                return _unready_inventory()
            if not _safe_provider_id(last_id) or last_id in seen_cursors:
                return _unready_inventory()
            cursor = last_id
        return _unready_inventory()

    def _list_page(self, cursor: str | None, *, timeout: float) -> Any:
        files = _get_value(_get_value(self._client, "vector_stores"), "files")
        list_files = _get_value(files, "list")
        if not callable(list_files):
            raise RuntimeError("vector_list_unavailable")
        arguments: dict[str, Any] = {
            "vector_store_id": self._vector_store_id,
            "limit": VECTOR_LIST_PAGE_SIZE,
            "timeout": timeout,
        }
        if cursor is not None:
            arguments["after"] = cursor
        return list_files(**arguments)


def _expected_inventory(value: Any) -> dict[str, tuple[str, str]] | None:
    rows = _get_value(value, "files")
    if not isinstance(rows, list) or not rows or len(rows) > 200:
        return None
    expected: dict[str, tuple[str, str]] = {}
    for row in rows:
        identifier = _get_value(row, "file_id", _get_value(row, "id"))
        filename = _safe_basename(_get_value(row, "filename"))
        digest = _get_value(row, "digest", _get_value(row, "sha256"))
        if not _safe_provider_id(identifier) or filename is None or not _safe_digest(digest) or identifier in expected:
            return None
        expected[identifier] = (filename, digest)
    completed = _get_value(value, "completed_file_count", len(rows))
    if not isinstance(completed, int) or isinstance(completed, bool) or completed != len(rows):
        return None
    return expected


def _safe_digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST_PATTERN.fullmatch(value) is not None


def _safe_text_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value == unicodedata.normalize("NFC", value)
        and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _safe_provider_id(value: Any) -> bool:
    return (
        _safe_text_identifier(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is not None
    )


def _ready_inventory(
    expected: Mapping[str, tuple[str, str]],
    vector_attestation_digest: str,
    provider_attestation_digest: str,
    corpus_version: str,
) -> dict[str, Any]:
    files = [{"filename": filename, "digest": digest} for filename, digest in sorted(expected.values())]
    canonical = "\n".join(f"{row['filename']}\x00{row['digest']}" for row in files).encode("utf-8")
    return {
        "ready": True,
        "fresh": True,
        "count": len(files),
        "files": files,
        "inventory_digest": hashlib.sha256(canonical).hexdigest(),
        "vector_attestation_digest": vector_attestation_digest,
        "provider_attestation_digest": provider_attestation_digest,
        "corpus_version": corpus_version,
    }


def _unready_inventory() -> dict[str, Any]:
    return {"ready": False, "fresh": False, "count": 0, "files": []}


def _copy_inventory(inventory: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(inventory)
    files = result.get("files")
    if isinstance(files, list):
        result["files"] = [dict(row) if isinstance(row, Mapping) else row for row in files]
    return result


def build_file_inventory_provider(
    client: Any,
    *,
    vector_store_id: str,
    expected_inventory: Mapping[str, Any],
    vector_attestation_digest: str,
    provider_attestation_digest: str,
    model: str,
    sdk_version: str,
    corpus_version: str,
    clock: Callable[[], float] = time.monotonic,
    deadline_seconds: float = 5.0,
    attestation_expires_at: dt.datetime | None = None,
    wall_clock: Callable[[], dt.datetime] | None = None,
) -> VectorReadinessService:
    """Build the lazy callable accepted by ``OpenAISecurityChatClient.file_inventory``."""
    return VectorReadinessService(
        client,
        vector_store_id=vector_store_id,
        expected_inventory=expected_inventory,
        vector_attestation_digest=vector_attestation_digest,
        provider_attestation_digest=provider_attestation_digest,
        model=model,
        sdk_version=sdk_version,
        corpus_version=corpus_version,
        clock=clock,
        deadline_seconds=deadline_seconds,
        attestation_expires_at=attestation_expires_at,
        wall_clock=wall_clock,
    )

def build_file_search_tool(
    vector_store_id: str,
    *,
    max_num_results: int = 5,
) -> dict:
    """Return the Responses API hosted File Search tool configuration."""
    normalized_store_id = vector_store_id.strip() if isinstance(vector_store_id, str) else ""
    if not _safe_provider_id(normalized_store_id):
        raise ValueError("Vector Store ID가 필요합니다.")
    if not isinstance(max_num_results, int) or isinstance(max_num_results, bool) or not 1 <= max_num_results <= MAX_FILE_RESULTS_PER_CALL:
        raise ValueError("검색 결과 수는 1~50 사이여야 합니다.")
    return {
        "type": "file_search",
        "vector_store_ids": [normalized_store_id],
        "max_num_results": max_num_results,
    }


def is_file_search_call(item: Any) -> bool:
    """Return whether a response output item is a File Search call."""
    return _get_value(item, "type") == "file_search_call"


def normalize_file_citation(annotation: Any) -> dict | None:
    """Normalize a standalone citation without exposing provider file IDs."""
    if _get_value(annotation, "type") != "file_citation":
        return None
    filename = _safe_basename(_get_value(annotation, "filename"))
    if filename is None:
        filename = "등록된 보안 문서"
    return {"type": "file", "title": filename}


def admit_file_citations(
    output_text: str,
    claims: list[dict],
    output: list[Any],
    response_scope: str,
    ready_inventory: Any,
) -> list[dict] | None:
    """Admit File evidence or reject every File candidate.

    ``file_refs`` are zero-based annotation ordinals, never provider ``index``
    values.  All File annotations must be referenced exactly once and each must
    resolve to one result in one completed call and one fresh attested basename.
    Unused top-k result rows are retrieval noise and are intentionally ignored.
    """
    if not isinstance(output_text, str) or not _is_scope(response_scope):
        return None
    if not isinstance(output, list) or len(output) > MAX_RESPONSE_OUTPUT_ITEMS:
        return None
    attested_basenames = _ready_attested_basenames(ready_inventory)
    if attested_basenames is None:
        return None
    annotations = _output_text_annotations(output)
    if annotations is None or len(annotations) > MAX_RESPONSE_ANNOTATIONS:
        return None
    file_annotations = [
        (ordinal, annotation)
        for ordinal, annotation in enumerate(annotations)
        if _get_value(annotation, "type") == "file_citation"
    ]
    references = _claim_file_references(claims)
    if references is None:
        return None
    referenced_ordinals = [ordinal for _, ordinal in references]
    known_ordinals = {ordinal for ordinal, _ in file_annotations}
    if (
        len(referenced_ordinals) != len(set(referenced_ordinals))
        or set(referenced_ordinals) != known_ordinals
    ):
        return None

    results = _completed_results(output)
    if results is None:
        return None
    citations: list[dict] = []
    used_results: set[tuple[int, int]] = set()
    claim_by_annotation = dict(references)
    for annotation_ordinal, annotation in file_annotations:
        filename = _safe_basename(_get_value(annotation, "filename"))
        provider_file_id = _get_value(annotation, "file_id")
        if filename is None or not isinstance(provider_file_id, str) or not provider_file_id:
            return None
        if filename not in attested_basenames:
            return None
        matching_results = [
            result
            for result in results
            if _get_value(result[2], "file_id") == provider_file_id
            and _safe_basename(_get_value(result[2], "filename")) == filename
        ]
        if len(matching_results) != 1:
            return None
        call_ordinal, result_ordinal, _ = matching_results[0]
        identity = (call_ordinal, result_ordinal)
        if identity in used_results:
            return None
        used_results.add(identity)
        citations.append(
            {
                "evidence_id": f"file:{response_scope}:{call_ordinal}:{result_ordinal}",
                "type": "file",
                "title": filename,
                "claim_ordinal": claim_by_annotation[annotation_ordinal],
            }
        )
    return citations


def _claim_file_references(claims: Any) -> list[tuple[int, int]] | None:
    if not isinstance(claims, list) or len(claims) > 5:
        return None
    references: list[tuple[int, int]] = []
    for claim_ordinal, claim in enumerate(claims):
        refs = _get_value(claim, "file_refs", [])
        if not isinstance(refs, list) or len(refs) > 3:
            return None
        scope = _get_value(claim, "source_scope")
        if scope not in {"web", "file", "mixed"}:
            return None
        if scope == "web" and refs:
            return None
        for reference in refs:
            ordinal = _annotation_ordinal(reference)
            if ordinal is None:
                return None
            references.append((claim_ordinal, ordinal))
    return references


def _annotation_ordinal(reference: Any) -> int | None:
    if isinstance(reference, int) and not isinstance(reference, bool) and reference >= 0:
        return reference
    if isinstance(reference, dict):
        value = reference.get("annotation_ordinal")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _completed_results(output: list[Any]) -> list[tuple[int, int, Any]] | None:
    results: list[tuple[int, int, Any]] = []
    for call_ordinal, item in enumerate(output):
        if not is_file_search_call(item):
            continue
        if _get_value(item, "status") != "completed":
            continue
        call_results = _get_value(item, "results")
        if not isinstance(call_results, list) or len(call_results) > MAX_FILE_RESULTS_PER_CALL:
            return None
        results.extend((call_ordinal, result_ordinal, result) for result_ordinal, result in enumerate(call_results))
    return results


def _ready_attested_basenames(inventory: Any) -> set[str] | None:
    if not isinstance(inventory, dict) or inventory.get("ready") is not True or inventory.get("fresh") is not True:
        return None
    rows = inventory.get("files")
    if not isinstance(rows, list) or not rows:
        return None
    names: set[str] = set()
    for row in rows:
        filename = _safe_basename(_get_value(row, "filename", row if isinstance(row, str) else None))
        if filename is None or filename in names:
            return None
        names.add(filename)
    return names


def _output_text_annotations(output: list[Any]) -> list[Any] | None:
    annotation_parts: list[Any] = []
    total_parts = 0
    for item in output:
        if _get_value(item, "type") != "message":
            continue
        content = _get_value(item, "content", [])
        if not isinstance(content, list):
            return None
        total_parts += len(content)
        if total_parts > MAX_RESPONSE_CONTENT_PARTS:
            return None
        for part in content:
            if _get_value(part, "type") != "output_text":
                continue
            annotations = _get_value(part, "annotations", [])
            if not isinstance(annotations, list):
                return None
            if annotations:
                annotation_parts.append(annotations)
    if len(annotation_parts) > 1:
        return None
    return annotation_parts[0] if annotation_parts else []


def _safe_basename(value: Any) -> str | None:
    if not isinstance(value, str) or not value or value != unicodedata.normalize("NFC", value):
        return None
    if value in {".", ".."} or "/" in value or "\\" in value:
        return None
    return value


def _is_scope(value: object) -> bool:
    return isinstance(value, str) and len(value) == 24 and all(char in "0123456789abcdef" for char in value)


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
