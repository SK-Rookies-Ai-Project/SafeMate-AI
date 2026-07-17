import hashlib
import io
import json
import os
import tempfile
import unittest
import time
from types import SimpleNamespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import create_vector_store
from src.services.provider_attestation import AttestationError


class CreateVectorStoreTest(unittest.TestCase):
    def test_default_create_refuses_before_loading_credentials(self) -> None:
        output = io.StringIO()
        with (
            patch.object(create_vector_store, "load_dotenv") as load_dotenv,
            patch.dict(os.environ, {}, clear=True),
            redirect_stdout(output),
        ):
            exit_code = create_vector_store.main(["create"])

        self.assertEqual(exit_code, 4)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "refused", "reason": "publication_not_explicitly_gated"},
        )
        load_dotenv.assert_not_called()

    def test_gated_create_refuses_empty_manifest_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "manifest.json"
            manifest.write_text('{"version":"1","files":[]}', encoding="utf-8")
            output = io.StringIO()
            with (
                patch.object(create_vector_store, "KNOWLEDGE_DIR", root),
                patch.object(create_vector_store, "MANIFEST_PATH", manifest),
                patch.object(create_vector_store, "load_dotenv") as load_dotenv,
                patch.dict(
                    os.environ,
                    {"SAFEMATE_VECTOR_STORE_PUBLISH": "YES"},
                    clear=True,
                ),
                redirect_stdout(output),
            ):
                exit_code = create_vector_store.main(["create"])

        self.assertEqual(exit_code, 4)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "refused", "reason": "corpus_manifest_empty"},
        )
        load_dotenv.assert_not_called()

    def test_approved_files_requires_exact_reviewed_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = root / "guide.md"
            document.write_text("official guidance", encoding="utf-8")
            digest = hashlib.sha256(document.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "files": [
                            {
                                "filename": "guide.md",
                                "sha256": digest,
                                "official_url": "https://www.kisa.or.kr/guide",
                                "review_date": "2026-07-17",
                                "owner": "SafeMate",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                create_vector_store.approved_files(root, manifest), [document]
            )
            (root / "unreviewed.txt").write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(AttestationError, "corpus_unmanifested"):
                create_vector_store.approved_files(root, manifest)
    def test_snapshots_bind_manifest_and_corpus_bytes_before_provider_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = root / "guide.md"
            document.write_text("approved", encoding="utf-8")
            digest = hashlib.sha256(document.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            original_manifest = json.dumps({"version": "1", "files": [{
                "filename": "guide.md", "sha256": digest,
                "official_url": "https://www.kisa.or.kr/guide",
                "review_date": "2026-07-17", "owner": "SafeMate",
            }]}).encode()
            manifest.write_bytes(original_manifest)
            snapshots, manifest_bytes, snapshot_dir = create_vector_store._snapshot_approved_corpus(root, manifest)
            document.write_text("mutated", encoding="utf-8")
            manifest.write_text('{"version":"changed","files":[]}', encoding="utf-8")
            try:
                self.assertEqual(original_manifest, manifest_bytes)
                self.assertEqual(b"approved", snapshots[0].read_bytes())
                self.assertEqual(digest, hashlib.sha256(snapshots[0].read_bytes()).hexdigest())
            finally:
                import shutil
                shutil.rmtree(snapshot_dir)

    def test_health_is_read_only_and_requires_local_attestation(self) -> None:
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
            exit_code = create_vector_store.main(["health", "--json"])

        self.assertEqual(exit_code, 3)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "status": "unavailable",
                "reason": "attestation_not_configured",
                "store": "not_checked",
            },
        )


    def test_probe_uses_four_response_attempts_and_publishes_acyclic_inventory(self) -> None:
        class Responses:
            def __init__(self):
                self.calls = []
                text = "KISA guide"
                self.values = [
                    {"status": "completed", "output": [{"type": "reasoning", "encrypted_content": "opaque"}, {"type": "function_call", "name": "build_security_action_plan", "status": "completed", "call_id": "transient", "arguments": '{"user_goal":"general","observed_event":"unknown","event_explicitly_reported":false}'}]},
                    {"status": "completed", "output_text": "Plan complete", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Plan complete"}]}]},
                    {"status": "completed", "output_text": text, "output": [{"type": "web_search_call", "status": "completed", "action": {"sources": [{"url": "https://www.kisa.or.kr/guide"}]}}, {"type": "message", "content": [{"type": "output_text", "annotations": [{"type": "url_citation", "url": "https://www.kisa.or.kr/guide", "start_index": 0, "end_index": len(text)}]}]}]},
                    {"status": "completed", "output_text": "Guide", "output": [{"type": "file_search_call", "status": "completed", "results": [{"filename": "guide.md", "file_id": "file-private"}]}, {"type": "message", "content": [{"type": "output_text", "annotations": [{"type": "file_citation", "filename": "guide.md", "file_id": "file-private"}]}]}]},
                ]

            def create(self, **kwargs):
                self.calls.append(kwargs)

                def objectify(value):
                    if isinstance(value, dict):
                        return SimpleNamespace(**{key: objectify(item) for key, item in value.items()})
                    if isinstance(value, list):
                        return [objectify(item) for item in value]
                    return value

                return objectify(self.values.pop(0))

        class Client:
            def __init__(self, **kwargs):
                self.responses = Responses()
                self.vector_calls = []
                self.files = type(
                    "Uploads",
                    (),
                    {
                        "create": lambda _, **kwargs: (
                            self.vector_calls.append(("upload", kwargs)) or {"id": "file-private"}
                        )
                    },
                )()
                self.vector_stores = type("Stores", (), {})()
                self.vector_stores.create = lambda **kwargs: (
                    self.vector_calls.append(("store", kwargs)) or {"id": "transient-store-id"}
                )
                self.vector_stores.file_batches = type(
                    "Batches",
                    (),
                    {
                        "create": lambda _, **kwargs: (
                            self.vector_calls.append(("batch", kwargs)) or {"id": "batch-private"}
                        ),
                        "retrieve": lambda _, **kwargs: (
                            self.vector_calls.append(("poll", kwargs))
                            or {"status": "completed", "file_counts": {"completed": 1, "failed": 0, "in_progress": 0}}
                        ),
                    },
                )()
                self.vector_stores.files = type(
                    "Files",
                    (),
                    {
                        "list": lambda _, **kwargs: (
                            self.vector_calls.append(("inventory", kwargs))
                            or {"data": [{"id": "file-private", "filename": "guide.md"}], "has_more": False}
                        )
                    },
                )()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = root / "guide.md"
            document.write_text("approved", encoding="utf-8")
            client = Client()
            publication = []
            receipt = create_vector_store._probe_vector_store(
                [document], client_factory=lambda **_: client, api_key="secret", model="model",
                sdk_version="sdk", vector_attestation_path=root / "vector-inventory.json",
                corpus_digest="b" * 64, corpus_version="1",
                issued_at="2026-07-17T00:00:00Z", expires_at="2026-07-18T00:00:00Z",
                inventory_publication=publication,
            )
            inventory = json.loads(publication[0][1].read_text(encoding="utf-8"))
        self.assertEqual(4, len(client.responses.calls))
        self.assertEqual(["store", "upload", "batch", "poll", "inventory"], [name for name, _ in client.vector_calls])
        self.assertTrue(all(0 < kwargs["timeout"] <= create_vector_store.PROBE_DEADLINE_SECONDS for _, kwargs in client.vector_calls))
        self.assertEqual({"function": True, "web": True, "file": True, "store": True}, receipt["checks"])
        self.assertEqual(publication[0][0], receipt["vector_attestation_digest"])
        self.assertNotIn("provider_attestation_digest", inventory)
        self.assertEqual(
            {
                "schema", "sdk_version", "model", "vector_store_id", "corpus_version",
                "issued_at", "expires_at", "corpus_manifest_digest",
                "completed_file_count", "files",
            },
            set(inventory),
        )
        public_receipt = json.dumps(receipt)
        self.assertNotIn("secret", public_receipt)
        self.assertNotIn("file-private", public_receipt)
        self.assertNotIn("transient-store-id", public_receipt)
    def test_vector_digest_is_discovered_after_probe_and_inventory_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "provider.json"
            vector = root / "vector.json"
            with patch.dict(
                os.environ,
                {
                    "SAFEMATE_VECTOR_STORE_PUBLISH": "YES",
                    "OPENAI_INTEGRATION_COST_ACK": "YES",
                    "OPENAI_PROVIDER_CONTRACT_ATTESTATION_PATH": str(active),
                    "OPENAI_VECTOR_INVENTORY_ATTESTATION_PATH": str(vector),
                    "OPENAI_MODEL": "model",
                    "OPENAI_SDK_VERSION": "sdk",
                },
                clear=True,
            ):
                _, _, configured_path, _ = create_vector_store._validate_publication_prerequisites(
                    "reviewer", injected_client=True
                )
            first_digest, first_path = create_vector_store._publish_inventory_attestation(
                {
                    "schema": "safemate.vector_inventory_attestation.v1",
                    "sdk_version": "sdk",
                    "model": "model",
                    "vector_store_id": "private-store-1",
                    "corpus_version": "1",
                    "issued_at": "2026-07-17T00:00:00Z",
                    "expires_at": "2026-07-18T00:00:00Z",
                    "corpus_manifest_digest": "a" * 64,
                    "completed_file_count": 1,
                    "files": [{"file_id": "private-file-1", "filename": "guide.md", "sha256": "b" * 64}],
                },
                configured_path,
            )
            second_digest, second_path = create_vector_store._publish_inventory_attestation(
                {
                    "schema": "safemate.vector_inventory_attestation.v1",
                    "sdk_version": "sdk",
                    "model": "model",
                    "vector_store_id": "private-store-2",
                    "corpus_version": "1",
                    "issued_at": "2026-07-17T00:00:00Z",
                    "expires_at": "2026-07-18T00:00:00Z",
                    "corpus_manifest_digest": "a" * 64,
                    "completed_file_count": 1,
                    "files": [{"file_id": "private-file-2", "filename": "guide.md", "sha256": "b" * 64}],
                },
                configured_path,
            )
            first_value = json.loads(first_path.read_text(encoding="utf-8"))["vector_store_id"]
        self.assertNotEqual(first_digest, second_digest)
        self.assertNotEqual(first_path, second_path)
        self.assertTrue(first_path.name.startswith(first_digest))
        self.assertEqual(first_value, "private-store-1")

    def test_file_search_probe_accepts_sdk_object_shapes(self) -> None:
        response = SimpleNamespace(
            status="completed",
            output_text="Guide",
            output=[
                SimpleNamespace(
                    type="file_search_call",
                    status="completed",
                    results=[SimpleNamespace(filename="guide.md", file_id="file-private")],
                ),
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(
                        type="output_text",
                        annotations=[SimpleNamespace(
                            type="file_citation", filename="guide.md", file_id="file-private"
                        )],
                    )],
                ),
            ],
        )
        self.assertTrue(create_vector_store._has_file_citation(response, [Path("guide.md")]))
    def test_inventory_validator_matches_runtime_identifier_boundaries(self) -> None:
        def inventory() -> dict:
            return {
                "schema": "safemate.vector_inventory_attestation.v1",
                "sdk_version": "s" * 128,
                "model": "m" * 128,
                "vector_store_id": "v" * 128,
                "corpus_version": "2026-07",
                "issued_at": "2026-07-17T00:00:00Z",
                "expires_at": "2026-07-18T00:00:00Z",
                "corpus_manifest_digest": "a" * 64,
                "completed_file_count": 1,
                "files": [{"file_id": "f" * 128, "filename": "guide.md", "sha256": "b" * 64}],
            }

        self.assertEqual(inventory(), create_vector_store._validate_inventory_attestation(inventory()))
        cases = (
            ("sdk_version", " sdk"),
            ("model", "model\n"),
            ("model", "bad\x01"),
            ("model", "e\u0301"),
            ("model", "m" * 129),
            ("vector_store_id", "vs/private"),
            ("vector_store_id", "vs\\private"),
            ("corpus_version", "e\u0301"),
            ("files", [{"file_id": "file", "filename": "../guide.md", "sha256": "b" * 64}]),
            ("files", [{"file_id": "file", "filename": "guide\\name.md", "sha256": "b" * 64}]),
        )
        for field, invalid in cases:
            with self.subTest(field=field, invalid=repr(invalid)):
                value = inventory()
                value[field] = invalid
                with self.assertRaisesRegex(AttestationError, "invalid_vector_inventory_schema"):
                    create_vector_store._validate_inventory_attestation(value)
    def test_probe_rejects_missing_citation(self) -> None:
        response = {"status": "completed", "output": [{"type": "message", "content": [{"annotations": []}]}]}
        self.assertFalse(create_vector_store._has_official_web_citation(response))
        self.assertFalse(create_vector_store._has_file_citation(response, [Path("guide.md")]))

    def test_manifest_rejects_tampering_and_unsafe_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = root / "guide.md"
            document.write_text("approved", encoding="utf-8")
            entry = {
                "filename": "guide.md",
                "sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
                "official_url": "https://www.kisa.or.kr/guide",
                "review_date": "2026-07-17",
                "owner": "SafeMate",
            }
            manifest = root / "manifest.json"
            for field, value in (
                ("sha256", "g" * 64),
                ("filename", "../guide.md"),
                ("filename", "/tmp/guide.md"),
                ("official_url", "http://www.kisa.or.kr/guide"),
                ("review_date", "not-a-date"),
            ):
                candidate = dict(entry)
                candidate[field] = value
                manifest.write_text(json.dumps({"version": "1", "files": [candidate]}), encoding="utf-8")
                with self.subTest(field=field, value=value), self.assertRaises(AttestationError):
                    create_vector_store.approved_files(root, manifest)
            manifest.unlink()
            with self.assertRaises(AttestationError):
                create_vector_store.approved_files(root, manifest)
            manifest.write_text(json.dumps({"version": "1", "files": [entry]}), encoding="utf-8")
            document.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(AttestationError, "corpus_manifest_mismatch"):
                create_vector_store.approved_files(root, manifest)

    def test_manifest_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root / "outside.md"
            outside.write_text("approved", encoding="utf-8")
            document = root / "guide.md"
            document.symlink_to(outside)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "files": [{
                            "filename": "guide.md",
                            "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
                            "official_url": "https://www.kisa.or.kr/guide",
                            "review_date": "2026-07-17",
                            "owner": "SafeMate",
                        }],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(AttestationError, "corpus_manifest_mismatch"):
                create_vector_store.approved_files(root, manifest)

    def test_inventory_pagination_is_bounded_and_rejects_bad_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            files = []
            for name in ("one.md", "two.md"):
                path = root / name
                path.write_text(name, encoding="utf-8")
                files.append(path)

            class Files:
                def __init__(self, pages):
                    self.pages = pages
                    self.calls = []

                def list(self, **kwargs):
                    self.calls.append(kwargs)
                    return self.pages.pop(0)

            valid = Files([
                {"data": [{"id": "file-1", "filename": "one.md"}], "has_more": True, "last_id": "file-1"},
                {"data": [{"id": "file-2", "filename": "two.md"}], "has_more": False},
            ])
            client = type("Client", (), {"vector_stores": type("Stores", (), {"files": valid})()})()
            rows = create_vector_store._inventory_rows(
                client, "vs-private", files, deadline=time.monotonic() + 1, requests={"total": 0}
            )
            self.assertEqual(2, len(rows))
            self.assertEqual("file-1", valid.calls[1]["after"])

            for page in (
                {"data": [{"id": "file-1", "filename": "one.md"}], "has_more": True},
                {"data": [{"id": "file-1", "filename": "one.md"}], "has_more": True, "last_id": "wrong"},
            ):
                bad = Files([page])
                bad_client = type("Client", (), {"vector_stores": type("Stores", (), {"files": bad})()})()
                with self.subTest(page=page), self.assertRaisesRegex(AttestationError, "inventory_incomplete"):
                    create_vector_store._inventory_rows(
                        bad_client, "vs-private", files, deadline=time.monotonic() + 1, requests={"total": 0}
                    )

    def test_batch_poll_is_capped_and_rejects_never_terminal_status(self) -> None:
        class Uploads:
            def create(self, **kwargs):
                return {"id": "file-1"}

        class Batches:
            def __init__(self):
                self.retrieve_calls = []

            def create(self, **kwargs):
                return {"id": "batch-1"}

            def retrieve(self, **kwargs):
                self.retrieve_calls.append(kwargs)
                return {"status": "in_progress"}

        batches = Batches()
        client = type(
            "Client",
            (),
            {
                "files": Uploads(),
                "vector_stores": type("Stores", (), {"file_batches": batches})(),
            },
        )()
        with tempfile.TemporaryDirectory() as temp_dir:
            document = Path(temp_dir) / "guide.md"
            document.write_text("approved", encoding="utf-8")
            with patch.object(create_vector_store.time, "sleep"):
                with self.assertRaisesRegex(AttestationError, "upload_incomplete"):
                    create_vector_store._upload_batch_and_poll(
                        client,
                        "vs-private",
                        [document],
                        deadline=time.monotonic() + 1,
                        requests={"total": 0},
                    )
        self.assertEqual(create_vector_store.VECTOR_BATCH_POLL_LIMIT, len(batches.retrieve_calls))
        self.assertTrue(all("timeout" in kwargs for kwargs in batches.retrieve_calls))

    def test_vector_request_deadline_and_budget_are_fail_closed(self) -> None:
        with self.assertRaisesRegex(AttestationError, "vector_request_limit_exceeded"):
            create_vector_store._vector_request(
                {"total": create_vector_store.VECTOR_REQUEST_LIMIT},
                time.monotonic() + 1,
                lambda **kwargs: None,
            )
        calls = []
        with patch.object(create_vector_store.time, "monotonic", side_effect=[0.0, 1.0]):
            with self.assertRaisesRegex(AttestationError, "probe_deadline_exceeded"):
                create_vector_store._vector_request(
                    {"total": 0}, 1.0, lambda **kwargs: calls.append(kwargs)
                )
        self.assertEqual(1, len(calls))
        self.assertEqual(1.0, calls[0]["timeout"])

    def test_inventory_101_and_200_file_boundaries_use_at_most_two_pages(self) -> None:
        class Files:
            def __init__(self, pages):
                self.pages = pages
                self.calls = []

            def list(self, **kwargs):
                self.calls.append(kwargs)
                return self.pages.pop(0)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for count in (101, 200):
                paths = []
                rows = []
                for index in range(count):
                    path = root / f"{count}-{index}.md"
                    path.write_text(str(index), encoding="utf-8")
                    paths.append(path)
                    rows.append({"id": f"file-{index}", "filename": path.name})
                listed = Files(
                    [
                        {"data": rows[:100], "has_more": True, "last_id": "file-99"},
                        {"data": rows[100:], "has_more": False},
                    ]
                )
                client = type(
                    "Client", (), {"vector_stores": type("Stores", (), {"files": listed})()}
                )()
                inventory = create_vector_store._inventory_rows(
                    client,
                    "vs-private",
                    paths,
                    deadline=time.monotonic() + 1,
                    requests={"total": 0},
                )
                self.assertEqual(count, len(inventory))
                self.assertEqual(2, len(listed.calls))
                self.assertEqual("file-99", listed.calls[1]["after"])
    def test_completed_status_and_populated_untrusted_citations_are_rejected(self) -> None:
        class Responses:
            def create(self, **kwargs):
                return {"status": None, "output": []}

        with self.assertRaisesRegex(AttestationError, "probe_incomplete"):
            client = type("Client", (), {"responses": Responses()})()
            create_vector_store._response_call(
                client, deadline=time.monotonic() + 1, input="x"
            )
        web = {
            "status": "completed",
            "output_text": "bad source",
            "output": [
                {"type": "web_search_call", "status": "completed", "action": {"sources": [{"url": "https://evil.example/"}]}},
                {"type": "message", "content": [{"type": "output_text", "annotations": [{"type": "url_citation", "url": "https://evil.example/", "start_index": 0, "end_index": 10}]}]},
            ],
        }
        file_response = {
            "status": "completed",
            "output_text": "wrong file",
            "output": [
                {"type": "file_search_call", "status": "completed", "results": [{"status": "completed", "filename": "other.md", "file_id": "private-other"}]},
                {"type": "message", "content": [{"type": "output_text", "annotations": [{"type": "file_citation", "filename": "other.md", "file_id": "private-other"}]}]},
            ],
        }
        self.assertFalse(create_vector_store._has_official_web_citation(web))
        self.assertFalse(create_vector_store._has_file_citation(file_response, [Path("guide.md")]))

    def test_health_does_not_load_credentials_construct_clients_or_write(self) -> None:
        output = io.StringIO()
        with (
            patch.object(create_vector_store, "load_dotenv") as load_dotenv,
            patch.object(create_vector_store, "AttestationPublisher") as publisher,
            patch.dict(os.environ, {}, clear=True),
            redirect_stdout(output),
        ):
            self.assertEqual(3, create_vector_store.health_command())
        load_dotenv.assert_not_called()
        publisher.assert_not_called()
        self.assertEqual("unavailable", json.loads(output.getvalue())["status"])
if __name__ == "__main__":
    unittest.main()
