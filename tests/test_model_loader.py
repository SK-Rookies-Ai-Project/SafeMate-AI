import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.analyzers.model_loader import ModelLoadError, load_model


class ModelLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.models_dir = Path(self.temp_dir.name)
        self.artifact = self.models_dir / "message-v2.joblib"
        self.artifact.write_bytes(b"model artifact")
        self.manifest_path = self.models_dir / "manifest.json"
        self.entry = {
            "version": "message-v2",
            "filename": self.artifact.name,
            "sha256": hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
            "serializer": "joblib",
        }
        self._write_manifest(self.entry)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_manifest(self, entry: dict) -> None:
        self.manifest_path.write_text(
            json.dumps(
                {"schema_version": 1, "models": {"message": entry}}
            ),
            encoding="utf-8",
        )

    @patch("src.analyzers.model_loader.joblib.load", return_value={"ok": True})
    def test_loads_verified_model_and_manifest_version(self, mocked_load) -> None:
        loaded = load_model(
            "message",
            manifest_path=self.manifest_path,
            models_dir=self.models_dir,
        )

        self.assertEqual(loaded.model, {"ok": True})
        self.assertEqual(loaded.version, "message-v2")
        mocked_load.assert_called_once_with(self.artifact.resolve())

    def test_rejects_missing_model_file(self) -> None:
        self.artifact.unlink()
        with self.assertRaisesRegex(ModelLoadError, "missing"):
            load_model(
                "message",
                manifest_path=self.manifest_path,
                models_dir=self.models_dir,
            )

    def test_rejects_sha256_mismatch(self) -> None:
        self.artifact.write_bytes(b"tampered")
        with self.assertRaisesRegex(ModelLoadError, "SHA-256 mismatch"):
            load_model(
                "message",
                manifest_path=self.manifest_path,
                models_dir=self.models_dir,
            )

    def test_rejects_path_outside_models_directory(self) -> None:
        entry = dict(self.entry, filename="../message-v2.joblib")
        self._write_manifest(entry)
        with self.assertRaisesRegex(ModelLoadError, "escapes"):
            load_model(
                "message",
                manifest_path=self.manifest_path,
                models_dir=self.models_dir,
            )

    @patch("src.analyzers.model_loader.joblib.load", side_effect=ValueError("bad"))
    def test_wraps_deserialization_failure(self, _mocked_load) -> None:
        with self.assertRaisesRegex(ModelLoadError, "deserialize"):
            load_model(
                "message",
                manifest_path=self.manifest_path,
                models_dir=self.models_dir,
            )

    def test_rejects_invalid_manifest_schema(self) -> None:
        self.manifest_path.write_text('{"schema_version": 2}', encoding="utf-8")
        with self.assertRaisesRegex(ModelLoadError, "schema"):
            load_model(
                "message",
                manifest_path=self.manifest_path,
                models_dir=self.models_dir,
            )


if __name__ == "__main__":
    unittest.main()
