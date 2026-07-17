"""Bounded Vector Store publication and read-only provider-attestation health."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.file_search import admit_file_citations, build_file_search_tool
from src.services.provider_attestation import AttestationError, AttestationPublisher, canonical_json_bytes, health, sha256_hex
from src.services.security_action import (
    CUSTOM_FUNCTION_TOOL,
    FUNCTION_NAME,
    build_security_action_plan,
    canonical_action_plan_json,
    validate_phase_one_response,
)
from src.services.web_search import WEB_SEARCH_INCLUDE, admit_web_citations, build_web_search_tool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "knowledge_base"
MANIFEST_PATH = KNOWLEDGE_DIR / "manifest.json"
SUPPORTED_EXTENSIONS = {".docx", ".html", ".json", ".md", ".pdf", ".pptx", ".txt"}
MAX_FILES = 200
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_REVIEWER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{1,127}$")
RESPONSE_MAX_OUTPUT_TOKENS = 512
RESPONSE_MAX_TOOL_CALLS = 5
PROBE_DEADLINE_SECONDS = 60.0
VECTOR_BATCH_POLL_LIMIT = 8
VECTOR_REQUEST_LIMIT = 1 + MAX_FILES + 1 + VECTOR_BATCH_POLL_LIMIT + 2
PUBLICATION_CEILINGS = {
    "max_retries": 0,
    "responses": 4,
    "vector_operations": VECTOR_REQUEST_LIMIT,
    "max_output_tokens": RESPONSE_MAX_OUTPUT_TOKENS,
    "max_tool_calls": RESPONSE_MAX_TOOL_CALLS,
}


def _safe_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_digest(manifest_bytes: bytes) -> str:
    return hashlib.sha256(manifest_bytes).hexdigest()


def _corpus_version(manifest_bytes: bytes) -> str:
    try:
        version = json.loads(manifest_bytes)["version"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise AttestationError("corpus_manifest_invalid") from error
    if not isinstance(version, str) or not version:
        raise AttestationError("corpus_manifest_invalid")
    return version


def _required_environment(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise AttestationError("publication_prerequisite_missing")
    return value
def _safe_text_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value == unicodedata.normalize("NFC", value)
        and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _safe_basename(name: Any) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and unicodedata.normalize("NFC", name) == name
        and name not in {".", ".."}
        and "/" not in name
        and "\\" not in name
    )


def _load_manifest(manifest_path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        mode = os.lstat(manifest_path).st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise AttestationError("corpus_manifest_invalid")
        content = manifest_path.read_bytes()
        manifest = json.loads(content)
    except (OSError, json.JSONDecodeError) as error:
        raise AttestationError("corpus_manifest_invalid") from error
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"version", "files"}
        or not isinstance(manifest["version"], str)
        or not manifest["version"]
        or not isinstance(manifest["files"], list)
    ):
        raise AttestationError("corpus_manifest_invalid")
    return content, manifest


def _snapshot_approved_corpus(
    knowledge_dir: Path = KNOWLEDGE_DIR, manifest_path: Path = MANIFEST_PATH
) -> tuple[list[Path], bytes, Path]:
    """Bind reviewed manifest bytes to private immutable upload snapshots."""
    try:
        if knowledge_dir.is_symlink() or not knowledge_dir.is_dir():
            raise AttestationError("corpus_manifest_invalid")
        manifest_bytes, manifest = _load_manifest(manifest_path)
    except OSError as error:
        raise AttestationError("corpus_manifest_invalid") from error
    entries = manifest["files"]
    if not entries or len(entries) > MAX_FILES:
        raise AttestationError("corpus_manifest_empty")
    snapshot_dir = Path(tempfile.mkdtemp(prefix=".safemate-corpus-", dir=knowledge_dir))
    snapshots: list[Path] = []
    names: set[str] = set()
    try:
        os.chmod(snapshot_dir, 0o700)
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"filename", "sha256", "official_url", "review_date", "owner"}:
                raise AttestationError("corpus_manifest_invalid")
            name = entry["filename"]
            metadata = ("sha256", "official_url", "review_date", "owner")
            if (
                not _safe_basename(name)
                or name in names
                or Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS
                or any(not isinstance(entry[key], str) or not entry[key] for key in metadata)
                or not _DIGEST.fullmatch(entry["sha256"])
                or urlparse(entry["official_url"]).scheme != "https"
                or not urlparse(entry["official_url"]).netloc
            ):
                raise AttestationError("corpus_manifest_invalid")
            try:
                dt.date.fromisoformat(entry["review_date"])
                source_fd = os.open(knowledge_dir / name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                source_stat = os.fstat(source_fd)
                if not stat.S_ISREG(source_stat.st_mode):
                    raise AttestationError("corpus_manifest_mismatch")
                snapshot = snapshot_dir / name
                snapshot_fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    digest = hashlib.sha256()
                    while block := os.read(source_fd, 65536):
                        digest.update(block)
                        view = memoryview(block)
                        while view:
                            view = view[os.write(snapshot_fd, view):]
                    os.fsync(snapshot_fd)
                    os.fchmod(snapshot_fd, 0o400)
                finally:
                    os.close(snapshot_fd)
                    os.close(source_fd)
            except (OSError, ValueError) as error:
                raise AttestationError("corpus_manifest_mismatch") from error
            if digest.hexdigest() != entry["sha256"] or _digest_file(snapshot) != entry["sha256"]:
                raise AttestationError("corpus_manifest_mismatch")
            names.add(name)
            snapshots.append(snapshot)
        disk_documents = {path.name for path in knowledge_dir.iterdir() if path.is_file() and not path.is_symlink() and path.name != "manifest.json" and path.name != snapshot_dir.name and path.suffix.lower() in SUPPORTED_EXTENSIONS}
        if disk_documents != names:
            raise AttestationError("corpus_unmanifested")
        return snapshots, manifest_bytes, snapshot_dir
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise


def approved_files(knowledge_dir: Path = KNOWLEDGE_DIR, manifest_path: Path = MANIFEST_PATH) -> list[Path]:
    """Return the exact reviewed corpus, refusing unmanifested or changed documents."""
    snapshots, _, snapshot_dir = _snapshot_approved_corpus(knowledge_dir, manifest_path)
    try:
        return [knowledge_dir / path.name for path in snapshots]
    finally:
        shutil.rmtree(snapshot_dir, ignore_errors=True)


def health_command(*, collect_orphan_receipts: bool = False, older_than_days: int = 30) -> int:
    active_path = (os.getenv("OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH") or "").strip()
    protected_digest = (os.getenv("OPENAI_PROVIDER_CONTRACT_ATTESTATION_SHA256") or "").strip()
    if not active_path or not protected_digest:
        _safe_json({"status": "unavailable", "reason": "attestation_not_configured", "store": "not_checked"})
        return 3
    try:
        result = health(active_path, protected_digest, expected_sdk_version=os.getenv("OPENAI_SDK_VERSION") or None, expected_model=os.getenv("OPENAI_MODEL") or None)
        output: dict[str, Any] = {"status": result["status"], "attestation_digest": result["attestation_digest"], "receipt_digest": result["receipt_digest"], "store": "not_checked"}
        if collect_orphan_receipts:
            output["orphan_receipt_digests"] = AttestationPublisher(active_path).collect_orphan_receipts(older_than_days=older_than_days)
        _safe_json(output)
    except AttestationError as error:
        _safe_json({"status": "unavailable", "reason": error.code, "store": "not_checked"})
        return 3
    return 0


def _validate_publication_prerequisites(reviewer_id: str, *, injected_client: bool = False) -> tuple[str, str, Path, AttestationPublisher]:
    if os.getenv("SAFEMATE_VECTOR_STORE_PUBLISH") != "YES":
        raise AttestationError("publication_not_explicitly_gated")
    if os.getenv("OPENAI_INTEGRATION_COST_ACK") != "YES":
        raise AttestationError("cost_not_acknowledged")
    if not reviewer_id:
        raise AttestationError("reviewer_not_configured")
    if not _REVIEWER.fullmatch(reviewer_id):
        raise AttestationError("invalid_reviewer")
    active_path = _required_environment("OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH")
    vector_path = Path(_required_environment("OPENAI_VECTOR_INVENTORY_ATTESTATION_PATH"))
    if vector_path.is_symlink() or vector_path.parent.is_symlink() or not vector_path.parent.is_dir():
        raise AttestationError("invalid_vector_attestation_directory")
    model = _required_environment("OPENAI_MODEL")
    sdk_version = _required_environment("OPENAI_SDK_VERSION")
    if not injected_client and importlib.util.find_spec("openai") is None:
        raise AttestationError("sdk_unavailable")
    try:
        if not injected_client and importlib.metadata.version("openai") != sdk_version:
            raise AttestationError("sdk_version_mismatch")
    except importlib.metadata.PackageNotFoundError as error:
        raise AttestationError("sdk_unavailable") from error
    publisher = AttestationPublisher(active_path)
    publisher._validate_paths()
    if os.stat(vector_path.parent).st_dev != os.stat(publisher.active_path.parent).st_dev:
        raise AttestationError("cross_filesystem")
    return model, sdk_version, vector_path, publisher


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _require_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise AttestationError("probe_deadline_exceeded")

def _safe_provider_id(value: Any) -> bool:
    return _safe_text_identifier(value) and bool(_PROVIDER_ID.fullmatch(value))


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AttestationError("probe_deadline_exceeded")
    return remaining


def _vector_request(
    requests: dict[str, int],
    deadline: float,
    call: Callable[..., Any],
    **kwargs: Any,
) -> Any:
    if requests["total"] >= VECTOR_REQUEST_LIMIT:
        raise AttestationError("vector_request_limit_exceeded")
    timeout = _remaining_timeout(deadline)
    requests["total"] += 1
    response = call(timeout=timeout, **kwargs)
    _require_deadline(deadline)
    return response


def _upload_batch_and_poll(
    client: Any,
    store_id: str,
    files: list[Path],
    *,
    deadline: float,
    requests: dict[str, int],
) -> Any:
    file_ids: list[str] = []
    for path in files:
        with path.open("rb") as handle:
            uploaded = _vector_request(
                requests, deadline, client.files.create, file=handle, purpose="assistants"
            )
        file_id = _field(uploaded, "id")
        if not _safe_provider_id(file_id):
            raise AttestationError("upload_incomplete")
        file_ids.append(file_id)
    batch = _vector_request(
        requests,
        deadline,
        client.vector_stores.file_batches.create,
        vector_store_id=store_id,
        file_ids=file_ids,
    )
    batch_id = _field(batch, "id")
    if not _safe_provider_id(batch_id):
        raise AttestationError("upload_incomplete")
    for poll_number in range(VECTOR_BATCH_POLL_LIMIT):
        batch = _vector_request(
            requests,
            deadline,
            client.vector_stores.file_batches.retrieve,
            vector_store_id=store_id,
            batch_id=batch_id,
        )
        status = _field(batch, "status")
        if status == "completed":
            return batch
        if status in {"cancelled", "cancelling", "failed"}:
            raise AttestationError("upload_incomplete")
        if status != "in_progress" or poll_number == VECTOR_BATCH_POLL_LIMIT - 1:
            raise AttestationError("upload_incomplete")
        time.sleep(min(1.0, _remaining_timeout(deadline)))
    raise AttestationError("upload_incomplete")

def _inventory_rows(
    client: Any,
    store_id: str,
    files: list[Path],
    *,
    deadline: float,
    requests: dict[str, int],
) -> list[dict[str, str]]:
    expected = {path.name: _digest_file(path) for path in files}
    if any(not _safe_basename(path.name) for path in files):
        raise AttestationError("inventory_incomplete")
    inventory: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    cursor: str | None = None
    for page_number in range(2):
        kwargs: dict[str, Any] = {"vector_store_id": store_id, "limit": 100}
        if cursor is not None:
            kwargs["after"] = cursor
        page = _vector_request(requests, deadline, client.vector_stores.files.list, **kwargs)
        rows = _field(page, "data", [])
        has_more = _field(page, "has_more")
        if not isinstance(rows, list) or len(rows) > 100 or not isinstance(has_more, bool) or not rows:
            raise AttestationError("inventory_incomplete")
        for row in rows:
            file_id = _field(row, "id")
            filename = _field(row, "filename")
            if (
                not _safe_provider_id(file_id)
                or file_id in seen_ids
                or not isinstance(filename, str)
                or filename not in expected
                or any(item["filename"] == filename for item in inventory)
            ):
                raise AttestationError("inventory_incomplete")
            seen_ids.add(file_id)
            inventory.append({"file_id": file_id, "filename": filename, "sha256": expected[filename]})
        last_id = _field(page, "last_id")
        if has_more:
            if page_number == 1 or not isinstance(last_id, str) or not last_id or last_id != _field(rows[-1], "id"):
                raise AttestationError("inventory_incomplete")
            cursor = last_id
            continue
        if len(inventory) != len(files) or {row["filename"] for row in inventory} != set(expected):
            raise AttestationError("inventory_incomplete")
        return sorted(inventory, key=lambda row: row["filename"])
    raise AttestationError("inventory_incomplete")


def _validate_inventory_attestation(value: Any) -> dict[str, Any]:
    required = {
        "schema", "sdk_version", "model", "vector_store_id", "corpus_version",
        "issued_at", "expires_at", "corpus_manifest_digest",
        "completed_file_count", "files",
    }
    if not isinstance(value, dict) or set(value) != required or value["schema"] != "safemate.vector_inventory_attestation.v1":
        raise AttestationError("invalid_vector_inventory_schema")
    if (
        not all(_safe_text_identifier(value[field]) for field in ("sdk_version", "model"))
        or not _safe_provider_id(value["vector_store_id"])
        or not isinstance(value["corpus_version"], str)
        or not value["corpus_version"]
        or unicodedata.normalize("NFC", value["corpus_version"]) != value["corpus_version"]
        or not isinstance(value["issued_at"], str)
        or not isinstance(value["expires_at"], str)
    ):
        raise AttestationError("invalid_vector_inventory_schema")
    try:
        issued = dt.datetime.strptime(value["issued_at"], "%Y-%m-%dT%H:%M:%SZ")
        expires = dt.datetime.strptime(value["expires_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise AttestationError("invalid_vector_inventory_schema") from error
    if expires <= issued or expires - issued > dt.timedelta(days=30):
        raise AttestationError("invalid_vector_inventory_schema")
    if not _DIGEST.fullmatch(value["corpus_manifest_digest"]) or not isinstance(value["completed_file_count"], int) or isinstance(value["completed_file_count"], bool):
        raise AttestationError("invalid_vector_inventory_schema")
    files = value["files"]
    if not isinstance(files, list) or not files or len(files) > MAX_FILES or len(files) != value["completed_file_count"]:
        raise AttestationError("invalid_vector_inventory_schema")
    filenames: set[str] = set()
    file_ids: set[str] = set()
    for row in files:
        if (
            not isinstance(row, dict)
            or set(row) != {"file_id", "filename", "sha256"}
            or not _safe_provider_id(row["file_id"])
            or row["file_id"] in file_ids
            or not _safe_basename(row["filename"])
            or row["filename"] in filenames
            or not _DIGEST.fullmatch(row["sha256"])
        ):
            raise AttestationError("invalid_vector_inventory_schema")
        file_ids.add(row["file_id"])
        filenames.add(row["filename"])
    if files != sorted(files, key=lambda row: row["filename"]):
        raise AttestationError("invalid_vector_inventory_schema")
    return value


def _publish_inventory_attestation(value: dict[str, Any], configured_path: Path) -> tuple[str, Path]:
    """Durably publish an immutable Vector inventory before its receipt references it."""
    _validate_inventory_attestation(value)
    content = canonical_json_bytes(value)
    digest = sha256_hex(content)
    receipts_path = Path(f"{configured_path}.receipts")
    if receipts_path.exists() or receipts_path.is_symlink():
        if receipts_path.is_symlink() or not receipts_path.is_dir():
            raise AttestationError("invalid_vector_attestation_directory")
    else:
        receipts_path.mkdir(mode=0o700)
        directory_fd = os.open(receipts_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    if os.stat(receipts_path).st_dev != os.stat(configured_path.parent).st_dev:
        raise AttestationError("cross_filesystem")
    final_path = receipts_path / f"{digest}.json"
    temporary: Path | None = None
    descriptor = -1
    try:
        descriptor, name = tempfile.mkstemp(prefix=".vector-inventory-", dir=receipts_path)
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, final_path)
            temporary.unlink()
            temporary = None
            directory_fd = os.open(receipts_path, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError:
            pass
        mode = os.lstat(final_path).st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise AttestationError("nonregular_file")
        verified = final_path.read_bytes()
        if verified != content or sha256_hex(verified) != digest or canonical_json_bytes(json.loads(verified.decode("utf-8"))) != verified:
            raise AttestationError("vector_attestation_digest_collision")
        return digest, final_path
    finally:
        if descriptor != -1:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _output(response: Any) -> list[Any]:
    output = _field(response, "output", [])
    if not isinstance(output, list) or len(output) > 16:
        raise AttestationError("probe_shape_invalid")
    return output


def _response_call(client: Any, *, deadline: float, **kwargs: Any) -> Any:
    timeout = min(20.0, _remaining_timeout(deadline))
    response = client.responses.create(
        store=False, max_output_tokens=RESPONSE_MAX_OUTPUT_TOKENS,
        timeout=timeout, **kwargs,
    )
    _require_deadline(deadline)
    if _field(response, "status") != "completed":
        raise AttestationError("probe_incomplete")
    return response


def _function_item(response: Any) -> Any:
    items = [item for item in _output(response) if _field(item, "type") == "function_call" and _field(item, "name") == FUNCTION_NAME]
    if len(items) != 1 or not isinstance(_field(items[0], "call_id"), str) or not isinstance(_field(items[0], "arguments"), str):
        raise AttestationError("function_probe_unproven")
    return items[0]


def _has_encrypted_reasoning(response: Any) -> bool:
    return any(
        _field(item, "type") == "reasoning" and isinstance(_field(item, "encrypted_content"), str) and _field(item, "encrypted_content")
        for item in _output(response)
    )


def _response_text(response: Any) -> str | None:
    text = _field(response, "output_text")
    if isinstance(text, str) and text:
        return text
    for item in _output(response):
        for content in _field(item, "content", []) or []:
            candidate = _field(content, "text")
            if isinstance(candidate, str) and candidate:
                return candidate
    return None
def _message_text(item: Any) -> str | None:
    if _field(item, "type") != "message":
        return None
    for content in _field(item, "content", []) or []:
        candidate = _field(content, "text")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None



def _has_official_web_citation(response: Any) -> bool:
    text = _response_text(response)
    if text is None:
        return False
    citations = admit_web_citations(text, [{"text": text}], _output(response), "0" * 24)
    return isinstance(citations, list) and bool(citations)


def _has_file_citation(response: Any, approved_files: list[Path]) -> bool:
    output = _output(response)
    file_search_calls = [item for item in output if _field(item, "type") == "file_search_call"]
    if len(file_search_calls) != 1 or _field(file_search_calls[0], "status") != "completed":
        return False
    results = _field(file_search_calls[0], "results", [])
    if not isinstance(results, list) or not results:
        return False
    for result in results:
        if not isinstance(_field(result, "filename"), str) or not isinstance(_field(result, "file_id"), str):
            return False
    annotations = [
        annotation
        for item in output
        for content in _field(item, "content", []) or []
        for annotation in _field(content, "annotations", []) or []
        if _field(annotation, "type") == "file_citation"
    ]
    if not annotations:
        return False
    citations = admit_file_citations(
        _response_text(response) or "",
        [{"source_scope": "file", "file_refs": list(range(len(annotations)))}],
        output,
        "0" * 24,
        {"ready": True, "fresh": True, "files": [{"filename": path.name} for path in approved_files]},
    )
    return isinstance(citations, list) and bool(citations)


def _probe_vector_store(
    files: list[Path],
    *,
    client_factory: Callable[..., Any],
    api_key: str,
    model: str,
    sdk_version: str,
    vector_attestation_path: Path,
    corpus_digest: str,
    corpus_version: str,
    issued_at: str,
    expires_at: str,
    inventory_publication: list[tuple[str, Path]],
) -> dict[str, Any]:
    deadline = time.monotonic() + PROBE_DEADLINE_SECONDS
    vector_requests = {"total": 0}
    client = client_factory(api_key=api_key, max_retries=0, timeout=PROBE_DEADLINE_SECONDS)
    store = _vector_request(
        vector_requests,
        deadline,
        client.vector_stores.create,
        name="SafeMate Official Security Knowledge Base",
        description="Reviewed SafeMate security corpus",
    )
    store_id = _field(store, "id")
    if not _safe_provider_id(store_id):
        raise AttestationError("upload_incomplete")
    batch = _upload_batch_and_poll(
        client, store_id, files, deadline=deadline, requests=vector_requests
    )
    counts = _field(batch, "file_counts")
    completed = _field(counts, "completed")
    upload_completed = (
        _field(batch, "status") == "completed"
        and completed == len(files)
        and _field(counts, "failed") in (0, None)
        and _field(counts, "in_progress") in (0, None)
    )
    if not upload_completed:
        raise AttestationError("upload_incomplete")
    inventory = _inventory_rows(
        client, store_id, files, deadline=deadline, requests=vector_requests
    )
    if not 1 <= vector_requests["total"] <= VECTOR_REQUEST_LIMIT:
        raise AttestationError("vector_operations_unproven")

    first = _response_call(
        client, deadline=deadline, model=model, input="Build a security action plan using the required enum values.",
        tools=[CUSTOM_FUNCTION_TOOL], tool_choice={"type": "function", "name": FUNCTION_NAME},
        parallel_tool_calls=False, include=["reasoning.encrypted_content"],
        max_tool_calls=RESPONSE_MAX_TOOL_CALLS, reasoning={"effort": "low"},
    )
    validated_phase_one = validate_phase_one_response(first)
    if validated_phase_one is None:
        raise AttestationError("function_probe_unproven")
    replay, function_call = validated_phase_one
    function_check = _has_encrypted_reasoning(first)
    if not function_check:
        raise AttestationError("encrypted_replay_unproven")
    try:
        arguments = json.loads(_field(function_call, "arguments"))
        action_output = canonical_action_plan_json(build_security_action_plan(arguments, None, "unknown"))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise AttestationError("function_probe_unproven") from error
    replay.append({"type": "function_call_output", "call_id": _field(function_call, "call_id"), "output": action_output})
    second = _response_call(
        client, deadline=deadline, model=model, input=replay, tools=[], tool_choice="none",
        parallel_tool_calls=False, max_tool_calls=RESPONSE_MAX_TOOL_CALLS,
    )
    terminal = _output(second)[-1] if _output(second) else None
    terminal_text = _message_text(terminal)
    if (
        not isinstance(terminal_text, str)
        or not terminal_text.strip()
        or any(isinstance(_field(item, "type"), str) and _field(item, "type").endswith("_call") for item in _output(second))
    ):
        raise AttestationError("encrypted_replay_unproven")
    web = _response_call(
        client, deadline=deadline, model=model, input="Use one official Korean security source and cite it.",
        tools=[build_web_search_tool()], tool_choice="auto", include=[WEB_SEARCH_INCLUDE],
        max_tool_calls=RESPONSE_MAX_TOOL_CALLS,
    )
    file_response = _response_call(
        client, deadline=deadline, model=model, input="Retrieve and cite one approved corpus document.",
        tools=[build_file_search_tool(store_id)], tool_choice="auto",
        include=["file_search_call.results"], max_tool_calls=RESPONSE_MAX_TOOL_CALLS,
    )
    checks = {
        "function": function_check and bool(terminal_text.strip()),
        "web": _has_official_web_citation(web),
        "file": _has_file_citation(file_response, files),
        "store": upload_completed and len(inventory) == len(files),
    }
    if not all(checks.values()):
        raise AttestationError("provider_check_unproven")
    vector_digest, vector_path = _publish_inventory_attestation(
        {
            "schema": "safemate.vector_inventory_attestation.v1",
            "sdk_version": sdk_version,
            "model": model,
            "vector_store_id": store_id,
            "corpus_version": corpus_version,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "corpus_manifest_digest": corpus_digest,
            "completed_file_count": len(inventory),
            "files": inventory,
        },
        vector_attestation_path,
    )
    inventory_publication.append((vector_digest, vector_path))
    return {
        "schema": "safemate.provider_probe_receipt.v1", "sdk_version": sdk_version, "model": model,
        "probed_at": issued_at,
        "ceilings": PUBLICATION_CEILINGS, "checks": checks,
        "counts": {"approved_files": len(files), "completed_files": completed, "response_attempts": 4},
        "states": {
            "file_search": "completed" if checks["file"] else "failed",
            "function_replay": "completed" if checks["function"] else "failed",
            "upload": "completed" if checks["store"] else "failed",
            "web_search": "completed" if checks["web"] else "failed",
        },
        "vector_attestation_digest": vector_digest, "corpus_manifest_digest": corpus_digest,
    }


def create_command(*, reviewer_id: str | None = None, client_factory: Callable[..., Any] | None = None) -> int:
    """Run the sole explicit Vector publication path; all provider work is injectable."""
    reviewer = (reviewer_id or os.getenv("SAFEMATE_PROVIDER_REVIEWER_ID") or "").strip()
    try:
        if os.getenv("SAFEMATE_VECTOR_STORE_PUBLISH") != "YES":
            raise AttestationError("publication_not_explicitly_gated")
        snapshots, manifest_bytes, snapshot_dir = _snapshot_approved_corpus()
        try:
            model, sdk_version, vector_attestation_path, publisher = _validate_publication_prerequisites(
                reviewer, injected_client=client_factory is not None
            )
            corpus_digest = _manifest_digest(manifest_bytes)
            corpus_version = _corpus_version(manifest_bytes)
            load_dotenv(PROJECT_ROOT / ".env")
            api_key = _required_environment("OPENAI_API_KEY")
            factory = client_factory
            if factory is None:
                from openai import OpenAI
                factory = OpenAI
            now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
            issued_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            expires_at = (now + dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            inventory_publication: list[tuple[str, Path]] = []
            provider_work_started = False

            def probe() -> dict[str, Any]:
                nonlocal provider_work_started
                provider_work_started = True
                return _probe_vector_store(
                    snapshots, client_factory=factory, api_key=api_key, model=model, sdk_version=sdk_version,
                    vector_attestation_path=vector_attestation_path, corpus_digest=corpus_digest,
                    corpus_version=corpus_version, issued_at=issued_at, expires_at=expires_at,
                    inventory_publication=inventory_publication,
                )

            result = publisher.publish_transaction(
                probe,
                reviewer_id=reviewer,
                issued_at=issued_at,
                expires_at=expires_at,
            )
            if len(inventory_publication) != 1:
                raise AttestationError("vector_attestation_unpublished")
        finally:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
    except AttestationError as error:
        _safe_json({"status": "refused", "reason": error.code})
        return 4
    except Exception:
        _safe_json(
            {
                "status": "refused",
                "reason": "probe_failed",
                "diagnostic": "unexpected_post_cost_failure" if "provider_work_started" in locals() and provider_work_started else "unexpected_pre_cost_failure",
            }
        )
        return 4
    _safe_json({"status": "published", "attestation_digest": result["attestation_digest"], "receipt_digest": result["receipt_digest"], "vector_attestation_digest": inventory_publication[0][0], "vector_attestation_path": str(inventory_publication[0][1])})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    health_parser = commands.add_parser("health")
    health_parser.add_argument("--json", action="store_true", required=True)
    health_parser.add_argument("--collect-orphan-receipts", action="store_true")
    health_parser.add_argument("--older-than-days", type=int, default=30)
    create_parser = commands.add_parser("create")
    create_parser.add_argument("--reviewer-id")
    args = parser.parse_args(argv)
    if args.command == "health":
        return health_command(collect_orphan_receipts=args.collect_orphan_receipts, older_than_days=args.older_than_days)
    return create_command(reviewer_id=args.reviewer_id)


if __name__ == "__main__":
    sys.exit(main())
