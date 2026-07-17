import datetime as dt
import copy
import fcntl
import os
import tempfile
import unittest
from pathlib import Path

from src.services.provider_attestation import (
    AttestationError,
    AttestationPublisher,
    canonical_json_bytes,
    health,
    parse_canonical_json,
    sha256_hex,
)


class ProviderAttestationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.active = Path(self.directory.name) / "active.json"
        self.receipt = {
            "schema": "safemate.provider_probe_receipt.v1",
            "sdk_version": "1.0", "model": "gpt-test", "probed_at": "2026-07-17T00:00:00Z",
            "ceilings": {
                "max_retries": 0,
                "responses": 4,
                "vector_operations": 212,
                "max_output_tokens": 512,
                "max_tool_calls": 5,
            },
            "checks": {"function": True, "web": True, "file": True, "store": True},
            "vector_attestation_digest": "a" * 64, "corpus_manifest_digest": "b" * 64,
            "counts": {"approved_files": 1, "completed_files": 1, "response_attempts": 4},
            "states": {
                "file_search": "completed",
                "function_replay": "completed",
                "upload": "completed",
                "web_search": "completed",
            },
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def publish(self, publisher=None):
        return (publisher or AttestationPublisher(self.active)).publish(
            self.receipt, reviewer_id="reviewer-1", issued_at="2026-07-17T00:00:00Z", expires_at="2026-07-18T00:00:00Z"
        )

    def test_canonical_rejection(self) -> None:
        for content in (b'{"a":1,"a":2}', b'{"a":1.0}', b'{"a":1}\n'):
            with self.assertRaises(AttestationError):
                parse_canonical_json(content)
        with self.assertRaises(AttestationError):
            canonical_json_bytes({"text": "e\u0301"})

    def test_receipt_nested_schemas_are_closed_and_semantically_consistent(self) -> None:
        mutations = (
            ("ceilings", {"responses": 4}),
            ("ceilings", {**self.receipt["ceilings"], "unexpected": 0}),
            ("ceilings", {**self.receipt["ceilings"], "responses": 3}),
            ("ceilings", {**self.receipt["ceilings"], "max_retries": False}),
            ("ceilings", {**self.receipt["ceilings"], "responses": True}),
            ("checks", {"function": True, "web": True, "file": True, "other": True}),
            ("checks", {**self.receipt["checks"], "unexpected": True}),
            ("checks", {**self.receipt["checks"], "store": False}),
            ("counts", {"approved_files": 1, "completed_files": 1}),
            ("counts", {**self.receipt["counts"], "unexpected": 1}),
            ("counts", {**self.receipt["counts"], "completed_files": 2}),
            ("counts", {**self.receipt["counts"], "response_attempts": 3}),
            ("counts", {**self.receipt["counts"], "approved_files": 0, "completed_files": 0}),
            ("states", {"upload": "completed"}),
            ("states", {**self.receipt["states"], "unexpected": "completed"}),
            ("states", {**self.receipt["states"], "upload": "pending"}),
        )
        for field, replacement in mutations:
            with self.subTest(field=field, replacement=replacement):
                receipt = copy.deepcopy(self.receipt)
                receipt[field] = replacement
                with self.assertRaisesRegex(AttestationError, "invalid_schema"):
                    AttestationPublisher(self.active).publish(
                        receipt,
                        reviewer_id="reviewer-1",
                        issued_at="2026-07-17T00:00:00Z",
                        expires_at="2026-07-18T00:00:00Z",
                    )

    def test_first_receipt_directory_publication_fsyncs_parent_before_receipt_write(self) -> None:
        checkpoints: list[str] = []
        self.publish(AttestationPublisher(self.active, failure_injector=checkpoints.append))
        self.assertLess(
            checkpoints.index("receipt_directory_created"),
            checkpoints.index("receipt_parent_directory_fsynced"),
        )
        self.assertLess(
            checkpoints.index("receipt_parent_directory_fsynced"),
            checkpoints.index("receipt_temp_created"),
        )

    def test_health_requires_aware_current_time_with_strict_window_edges(self) -> None:
        result = self.publish()
        with self.assertRaisesRegex(AttestationError, "attestation_not_issued"):
            health(self.active, result["attestation_digest"], now=dt.datetime(2026, 7, 16, 23, 59, 59, tzinfo=dt.timezone.utc))
        with self.assertRaisesRegex(AttestationError, "attestation_expired"):
            health(self.active, result["attestation_digest"], now=dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc))
        with self.assertRaisesRegex(AttestationError, "invalid_current_time"):
            health(self.active, result["attestation_digest"], now=dt.datetime(2026, 7, 17))
        ready = health(self.active, result["attestation_digest"], now=dt.datetime(2026, 7, 17, tzinfo=dt.timezone.utc))
        self.assertEqual("a" * 64, ready["vector_attestation_digest"])
    def test_health_rejects_tamper_and_digest_mismatch_without_network(self) -> None:
        result = self.publish()
        self.assertEqual("ready", health(self.active, result["attestation_digest"], now=dt.datetime(2026, 7, 17, tzinfo=dt.timezone.utc))["status"])
        with self.assertRaisesRegex(AttestationError, "attestation_digest_mismatch"):
            health(self.active, "0" * 64)
        self.active.write_bytes(b"{}")
        with self.assertRaises(AttestationError):
            health(self.active, result["attestation_digest"])

    def test_precommit_failure_preserves_old_pointer_and_orphan_is_safe(self) -> None:
        old = self.publish()
        before = self.active.read_bytes()
        self.receipt["corpus_manifest_digest"] = "c" * 64
        def fail(boundary):
            if boundary == "before_pointer_replace":
                raise AttestationError("injected")
        with self.assertRaisesRegex(AttestationError, "injected"):
            self.publish(AttestationPublisher(self.active, failure_injector=fail))
        self.assertEqual(before, self.active.read_bytes())
        self.assertEqual("ready", health(self.active, old["attestation_digest"], now=dt.datetime(2026, 7, 17, tzinfo=dt.timezone.utc))["status"])
        self.assertTrue(any(Path(f"{self.active}.receipts").iterdir()))

    def test_pointer_is_replaced_last(self) -> None:
        self.publish()
        old = self.active.read_bytes()
        def check(boundary):
            if boundary == "before_pointer_replace":
                self.assertEqual(old, self.active.read_bytes())
        self.receipt["corpus_manifest_digest"] = "c" * 64
        self.publish(AttestationPublisher(self.active, failure_injector=check))
        self.assertNotEqual(old, self.active.read_bytes())

    def test_idempotence_and_receipt_tamper(self) -> None:
        first = self.publish()
        self.assertEqual(first, self.publish())
        receipt = Path(f"{self.active}.receipts") / f"{first['receipt_digest']}.json"
        receipt.write_bytes(b"{}")
        with self.assertRaisesRegex(AttestationError, "receipt_digest_mismatch"):
            health(self.active, first["attestation_digest"])

    def test_lock_contention_makes_no_pointer_change(self) -> None:
        lock = Path(f"{self.active}.lock")
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            with self.assertRaisesRegex(AttestationError, "writer_locked"):
                self.publish(AttestationPublisher(self.active, lock_timeout=0))
        finally:
            os.close(descriptor)
        self.assertFalse(self.active.exists())

    def test_symlink_and_nonregular_active_files_are_rejected(self) -> None:
        target = self.active.with_name("target")
        target.write_text("x")
        self.active.symlink_to(target)
        with self.assertRaisesRegex(AttestationError, "nonregular_file"):
            self.publish()


    def test_probe_callback_runs_after_lock_acquisition(self) -> None:
        checkpoints: list[str] = []
        publisher = AttestationPublisher(self.active, failure_injector=checkpoints.append)
        result = publisher.publish_transaction(
            lambda: self.receipt,
            reviewer_id="reviewer-1",
            issued_at="2026-07-17T00:00:00Z",
            expires_at="2026-07-18T00:00:00Z",
        )
        self.assertIn("lock_acquired", checkpoints)
        self.assertLess(checkpoints.index("lock_acquired"), checkpoints.index("before_probe"))
        self.assertEqual("ready", health(self.active, result["attestation_digest"], now=dt.datetime(2026, 7, 17, tzinfo=dt.timezone.utc))["status"])

    def test_contention_prevents_probe_callback(self) -> None:
        lock = Path(f"{self.active}.lock")
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        called = False
        try:
            def probe():
                nonlocal called
                called = True
                return self.receipt

            with self.assertRaisesRegex(AttestationError, "writer_locked"):
                AttestationPublisher(self.active, lock_timeout=0).publish_transaction(
                    probe,
                    reviewer_id="reviewer-1",
                    issued_at="2026-07-17T00:00:00Z",
                    expires_at="2026-07-18T00:00:00Z",
                )
        finally:
            os.close(descriptor)
        self.assertFalse(called)

    def test_temporal_window_and_pair_semantics_fail_closed(self) -> None:
        with self.assertRaisesRegex(AttestationError, "invalid_attestation_window"):
            AttestationPublisher(self.active).publish(
                self.receipt,
                reviewer_id="reviewer-1",
                issued_at="2026-07-18T00:00:00Z",
                expires_at="2026-07-17T00:00:00Z",
            )
        result = self.publish()
        value = parse_canonical_json(self.active.read_bytes())
        value["model"] = "other-model"
        self.active.write_bytes(canonical_json_bytes(value))
        with self.assertRaisesRegex(AttestationError, "attestation_receipt_mismatch"):
            health(self.active, sha256_hex(self.active.read_bytes()), now=dt.datetime(2026, 7, 17, tzinfo=dt.timezone.utc))
        self.assertNotEqual(result["attestation_digest"], sha256_hex(self.active.read_bytes()))

    def test_probe_time_is_half_open_and_not_future_dated_at_health(self) -> None:
        self.receipt["probed_at"] = "2026-07-18T00:00:00Z"
        with self.assertRaisesRegex(AttestationError, "attestation_receipt_mismatch"):
            AttestationPublisher(self.active).publish(
                self.receipt,
                reviewer_id="reviewer-1",
                issued_at="2026-07-17T00:00:00Z",
                expires_at="2026-07-18T00:00:00Z",
            )

        self.receipt["probed_at"] = "2026-07-17T01:00:00Z"
        result = self.publish()
        with self.assertRaisesRegex(AttestationError, "probe_not_completed"):
            health(
                self.active,
                result["attestation_digest"],
                now=dt.datetime(2026, 7, 17, 0, 30, tzinfo=dt.timezone.utc),
            )

    def test_orphan_collection_is_dry_run_and_keeps_active_receipt(self) -> None:
        self.publish()
        self.receipt["corpus_manifest_digest"] = "c" * 64
        current = self.publish()
        receipts = Path(f"{self.active}.receipts")
        active_receipt = receipts / f"{current['receipt_digest']}.json"
        before = active_receipt.read_bytes()
        lock = Path(f"{self.active}.lock")
        lock.unlink()
        reported = AttestationPublisher(self.active).collect_orphan_receipts(older_than_days=0)
        self.assertNotIn(current["receipt_digest"], reported)
        self.assertFalse(lock.exists())
        self.assertEqual(before, active_receipt.read_bytes())
if __name__ == "__main__":
    unittest.main()
