"""Versioned local-model loading with manifest integrity checks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from src.config import MODEL_MANIFEST_PATH, MODELS_DIR


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_SERIALIZERS = {"joblib"}


class ModelLoadError(RuntimeError):
    """Raised when a configured model cannot be safely loaded."""


@dataclass(frozen=True)
class LoadedModel:
    """Loaded artifact paired with its manifest-controlled public version."""

    model: Any
    version: str


def load_model(
    model_name: str,
    *,
    manifest_path: Path = MODEL_MANIFEST_PATH,
    models_dir: Path = MODELS_DIR,
) -> LoadedModel:
    """Verify and load a named model from the tracked manifest."""
    manifest = _read_manifest(manifest_path)
    models = manifest.get("models")
    if not isinstance(models, dict) or model_name not in models:
        raise ModelLoadError(f"Model '{model_name}' is not defined in the manifest.")

    entry = models[model_name]
    if not isinstance(entry, dict):
        raise ModelLoadError(f"Manifest entry for '{model_name}' must be an object.")

    version = entry.get("version")
    filename = entry.get("filename")
    expected_hash = entry.get("sha256")
    serializer = entry.get("serializer")
    if not isinstance(version, str) or not version.strip():
        raise ModelLoadError(f"Model '{model_name}' has an invalid version.")
    if not isinstance(filename, str) or not filename.strip():
        raise ModelLoadError(f"Model '{model_name}' has an invalid filename.")
    if not isinstance(expected_hash, str) or not _SHA256_PATTERN.fullmatch(
        expected_hash.lower()
    ):
        raise ModelLoadError(f"Model '{model_name}' has an invalid SHA-256 value.")
    if serializer not in SUPPORTED_SERIALIZERS:
        raise ModelLoadError(
            f"Model '{model_name}' uses unsupported serializer '{serializer}'."
        )

    root = models_dir.resolve()
    artifact_path = (root / filename).resolve()
    if artifact_path.parent != root:
        raise ModelLoadError(f"Model '{model_name}' path escapes the models directory.")
    if not artifact_path.is_file():
        raise ModelLoadError(f"Model file is missing: {artifact_path.name}")

    actual_hash = _sha256(artifact_path)
    if actual_hash != expected_hash.lower():
        raise ModelLoadError(f"SHA-256 mismatch for model '{model_name}'.")

    try:
        model = joblib.load(artifact_path)
    except Exception as exc:
        raise ModelLoadError(f"Failed to deserialize model '{model_name}'.") from exc
    return LoadedModel(model=model, version=version.strip())


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            manifest = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelLoadError(f"Unable to read model manifest: {path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ModelLoadError("Unsupported or invalid model manifest schema.")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
