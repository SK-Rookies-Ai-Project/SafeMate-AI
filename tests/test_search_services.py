import datetime as dt
import hashlib
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from src.services.file_search import (
    FILE_SEARCH_INCLUDE,
    MAX_FILE_RESULTS_PER_CALL,
    VECTOR_LIST_PAGE_SIZE,
    VectorReadinessService,
    admit_file_citations,
    build_attested_file_inventory_provider,
    build_file_search_tool,
    is_file_search_call,
    normalize_file_citation,
)
from src.services.web_search import (
    OFFICIAL_SOURCE_DOMAINS,
    WEB_SEARCH_INCLUDE,
    admit_web_citations,
    build_web_search_tool,
    is_official_source_url,
    is_web_search_call,
    normalize_web_citation,
)

EXPECTED_OFFICIAL_DOMAINS = (
    "kisa.or.kr",
    "boho.or.kr",
    "krcert.or.kr",
    "police.go.kr",
    "fss.or.kr",
    "privacy.go.kr",
    "pipc.go.kr",
    "ncsc.go.kr",
    "msit.go.kr",
    "gov.kr",
    "korea.kr",
)


class WebSearchServiceTest(unittest.TestCase):
    def test_builds_hosted_web_search_tool_with_independently_pinned_domains(self) -> None:
        self.assertEqual(OFFICIAL_SOURCE_DOMAINS, EXPECTED_OFFICIAL_DOMAINS)
        self.assertEqual(
            build_web_search_tool(),
            {
                "type": "web_search",
                "filters": {"allowed_domains": list(EXPECTED_OFFICIAL_DOMAINS)},
            },
        )
        self.assertEqual(WEB_SEARCH_INCLUDE, "web_search_call.action.sources")

    def test_rejects_unapproved_source_urls(self) -> None:
        self.assertTrue(is_official_source_url("https://www.kisa.or.kr/notice"))
        self.assertTrue(is_official_source_url("https://ecrm.police.go.kr/guide"))
        self.assertFalse(is_official_source_url("https://security.example/guide"))
        self.assertFalse(is_official_source_url("http://www.kisa.or.kr/notice"))
        self.assertFalse(
            is_official_source_url("https://kisa.or.kr@security.example/guide")
        )

    def test_accepts_every_pinned_domain_and_its_subdomains(self) -> None:
        for domain in EXPECTED_OFFICIAL_DOMAINS:
            with self.subTest(domain=domain):
                self.assertTrue(is_official_source_url(f"https://{domain}/guide"))
                self.assertTrue(is_official_source_url(f"https://notice.{domain}/guide"))

    def test_rejects_domain_confusion_and_nonstandard_ports(self) -> None:
        rejected = (
            "https://kisa.or.kr.evil.example/guide",
            "https://fakekisa.or.kr/guide",
            "https://kisa.or.kr:444/guide",
            "https://user:password@kisa.or.kr/guide",
        )
        for url in rejected:
            with self.subTest(url=url):
                self.assertFalse(is_official_source_url(url))

    def test_identifies_web_search_call(self) -> None:
        self.assertTrue(is_web_search_call({"type": "web_search_call"}))
        self.assertFalse(is_web_search_call({"type": "message"}))

    def test_normalizes_web_citation(self) -> None:
        citation = normalize_web_citation(
            SimpleNamespace(
                type="url_citation",
                title="공식 보안 안내",
                url="https://www.kisa.or.kr/guide",
            )
        )

        self.assertEqual(
            citation,
            {
                "type": "url",
                "title": "공식 보안 안내",
                "url": "https://www.kisa.or.kr/guide",
            },
        )
        self.assertIsNone(
            normalize_web_citation(
                {
                    "type": "url_citation",
                    "title": "검증되지 않은 출처",
                    "url": "https://security.example/guide",
                }
            )
        )
        self.assertIsNone(normalize_web_citation({"type": "file_citation"}))


class WebEvidenceAdmissionTest(unittest.TestCase):
    def test_admits_only_bound_web_evidence_with_literal_zero_based_id(self) -> None:
        text = "공식 안내를 확인하세요."
        output = [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"sources": [{"url": "https://www.kisa.or.kr/guide"}]},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "title": "KISA",
                                "url": "https://www.kisa.or.kr/guide",
                                "start_index": 0,
                                "end_index": len(text),
                            }
                        ],
                    }
                ],
            },
        ]
        self.assertEqual(
            admit_web_citations(
                text, [{"text": text}], output, "00112233445566778899aabb"
            ),
            [
                {
                    "evidence_id": "web:00112233445566778899aabb:0:0",
                    "type": "url",
                    "title": "KISA",
                    "url": "https://www.kisa.or.kr/guide",
                    "claim_ordinal": 0,
                }
            ],
        )

    def test_requires_annotation_to_be_wholly_contained_in_one_claim(self) -> None:
        text = "첫 주장. 둘째 주장."
        claims = [{"text": "첫 주장."}, {"text": "둘째 주장."}]

        def output(annotation, sources=None):
            return [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {"sources": sources or [{"url": "https://www.kisa.or.kr/guide"}]},
                },
                {"type": "message", "content": [{"type": "output_text", "annotations": [annotation]}]},
            ]

        base = {
            "type": "url_citation",
            "url": "https://www.kisa.or.kr/guide",
            "start_index": 0,
            "end_index": len("첫 주장."),
        }
        self.assertIsNotNone(admit_web_citations(text, claims, output(base), "00112233445566778899aabb"))
        for start, end in ((0, len(text)), (4, 8), (0, len("첫 주장.") + 1)):
            with self.subTest(start=start, end=end):
                annotation = {**base, "start_index": start, "end_index": end}
                self.assertIsNone(admit_web_citations(text, claims, output(annotation), "00112233445566778899aabb"))

    def test_rejects_web_source_suffix_and_redirect_ambiguity(self) -> None:
        text = "공식 안내"
        claims = [{"text": text}]
        annotation = {
            "type": "url_citation",
            "url": "https://www.kisa.or.kr/guide",
            "start_index": 0,
            "end_index": len(text),
        }
        for source in (
            "https://www.kisa.or.kr.evil.example/guide",
            "https://kisa.or.kr@security.example/guide",
            "https://www.kisa.or.kr/redirect?next=https://security.example/",
        ):
            with self.subTest(source=source):
                self.assertIsNone(
                    admit_web_citations(
                        text,
                        claims,
                        [
                            {"type": "web_search_call", "status": "completed", "action": {"sources": [{"url": source}]}},
                            {"type": "message", "content": [{"type": "output_text", "annotations": [annotation]}]},
                        ],
                        "00112233445566778899aabb",
                    )
                )

    def test_binds_offsets_to_escaped_claim_text(self) -> None:
        claim = '사용자가 "공식 안내"를 읽었습니다.'
        text = json.dumps(claim, ensure_ascii=False)[1:-1]
        annotation = {
            "type": "url_citation",
            "url": "https://www.kisa.or.kr/guide",
            "start_index": 0,
            "end_index": len(text),
        }
        output = [
            {"type": "web_search_call", "status": "completed", "action": {"sources": [{"url": "https://www.kisa.or.kr/guide"}]}},
            {"type": "message", "content": [{"type": "output_text", "annotations": [annotation]}]},
        ]
        self.assertIsNotNone(admit_web_citations(text, [{"text": claim}], output, "00112233445566778899aabb"))

class FileSearchServiceTest(unittest.TestCase):
    def test_builds_hosted_file_search_tool(self) -> None:
        self.assertEqual(
            build_file_search_tool("vs_test"),
            {
                "type": "file_search",
                "vector_store_ids": ["vs_test"],
                "max_num_results": 5,
            },
        )
        self.assertEqual(FILE_SEARCH_INCLUDE, "file_search_call.results")

    def test_rejects_blank_vector_store_id(self) -> None:
        with self.assertRaises(ValueError):
            build_file_search_tool("  ")

    def test_identifies_file_search_call(self) -> None:
        self.assertTrue(is_file_search_call({"type": "file_search_call"}))
        self.assertFalse(is_file_search_call({"type": "message"}))

    def test_normalizes_file_citation(self) -> None:
        citation = normalize_file_citation(
            SimpleNamespace(
                type="file_citation",
                filename="smishing_guide.pdf",
                file_id="file_test",
            )
        )

        self.assertEqual(
            citation,
            {
                "type": "file",
                "title": "smishing_guide.pdf",
            }
        )
        self.assertIsNone(normalize_file_citation({"type": "url_citation"}))


class _VectorFiles:
    def __init__(self, pages, *, gate=None, advance=None) -> None:
        self.pages = list(pages)
        self.calls = []
        self.gate = gate
        self.advance = advance
        self.entered = threading.Event()

    def list(self, **kwargs):
        self.calls.append(kwargs)
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(timeout=1)
        if self.advance is not None:
            self.advance()
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


class AttestedVectorInventoryProviderTest(unittest.TestCase):
    def _attestation(self, **overrides):
        value = {
            "schema": "safemate.vector_inventory_attestation.v1",
            "sdk_version": "1.0",
            "model": "gpt-test",
            "vector_store_id": "vs_private",
            "corpus_version": "2026-07",
            "issued_at": "2026-07-01T00:00:00Z",
            "expires_at": "2026-07-31T00:00:00Z",
            "corpus_manifest_digest": "d" * 64,
            "completed_file_count": 1,
            "files": [{"file_id": "file_private", "filename": "guide.pdf", "sha256": "c" * 64}],
        }
        value.update(overrides)
        return value

    def _provider(self, value, protected_digest=None, provider_vector_digest=None):
        content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        vector_digest = protected_digest or hashlib.sha256(content).hexdigest()
        with tempfile.NamedTemporaryFile() as handle:
            handle.write(content)
            handle.flush()
            files = _VectorFiles([{"data": [{"file_id": "file_private", "status": "completed"}], "has_more": False, "last_id": None}])
            with patch(
                "src.services.file_search.provider_health",
                return_value={"vector_attestation_digest": provider_vector_digest or vector_digest},
            ):
                provider = build_attested_file_inventory_provider(
                    SimpleNamespace(vector_stores=SimpleNamespace(files=files)),
                    vector_store_id="vs_private",
                    model="gpt-test",
                    sdk_version="1.0",
                    provider_attestation_digest="b" * 64,
                    attestation_path=handle.name,
                    protected_digest=vector_digest,
                    provider_attestation_path="provider.json",
                    now=lambda: dt.datetime(2026, 7, 15, tzinfo=dt.timezone.utc),
                )
            return provider, files

    def test_valid_attestation_is_lazy_then_returns_safe_ready_inventory(self):
        provider, files = self._provider(self._attestation())
        self.assertEqual(files.calls, [])
        inventory = provider()
        self.assertTrue(inventory["ready"])
        self.assertEqual(files.calls[0]["vector_store_id"], "vs_private")
        self.assertNotIn("file_private", repr(inventory))
        self.assertNotIn("vs_private", repr(inventory))

    def test_invalid_attestation_never_reaches_vector_inventory(self):
        cases = (
            self._attestation(model="other"),
            self._attestation(sdk_version="2.0"),
            self._attestation(vector_store_id="vs_other"),
            self._attestation(corpus_manifest_digest="not-a-digest"),
            self._attestation(expires_at="2026-07-02T00:00:00Z"),
        )
        for value in cases:
            with self.subTest(value=value["model"]):
                provider, files = self._provider(value)
                self.assertFalse(provider()["ready"])
                self.assertEqual(files.calls, [])
        provider, files = self._provider(self._attestation(), protected_digest="0" * 64)
        self.assertFalse(provider()["ready"])
        self.assertEqual(files.calls, [])
    def test_rejects_stale_provider_vector_digest_pair_without_vector_io(self):
        provider, files = self._provider(
            self._attestation(),
            provider_vector_digest="e" * 64,
        )
        self.assertFalse(provider()["ready"])
        self.assertEqual(files.calls, [])

    def test_rejects_unsafe_vector_and_file_provider_ids(self):
        unsafe_ids = (" vs_private", "vs/private", "vs\\private", "vs\tprivate", "v" * 129)
        for identifier in unsafe_ids:
            with self.subTest(identifier=repr(identifier)):
                provider, files = self._provider(self._attestation(vector_store_id=identifier))
                self.assertFalse(provider()["ready"])
                self.assertEqual(files.calls, [])

    def test_rejects_unsafe_attested_file_identifier_without_vector_io(self):
        files = _VectorFiles([])
        service = VectorReadinessService(
            SimpleNamespace(vector_stores=SimpleNamespace(files=files)),
            vector_store_id="vs_private",
            expected_inventory={
                "completed_file_count": 1,
                "files": [{"file_id": "../file_private", "filename": "guide.pdf", "digest": "c" * 64}],
            },
            vector_attestation_digest="a" * 64,
            provider_attestation_digest="b" * 64,
            model="gpt-test",
            sdk_version="1.0",
            corpus_version="2026-07",
        )
        self.assertFalse(service()["ready"])
        self.assertEqual(files.calls, [])
class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class VectorReadinessServiceTest(unittest.TestCase):
    digest = "a" * 64
    provider_digest = "b" * 64

    def _service(self, pages, *, clock=None, **overrides):
        self.files = _VectorFiles(
            pages,
            gate=overrides.pop("gate", None),
            advance=overrides.pop("advance", None),
        )
        values = {
            "vector_store_id": "vs_private",
            "expected_inventory": {
                "completed_file_count": 2,
                "files": [
                    {"file_id": "file_private_one", "filename": "guide.pdf", "digest": "c" * 64},
                    {"file_id": "file_private_two", "filename": "notice.pdf", "digest": "d" * 64},
                ],
            },
            "vector_attestation_digest": self.digest,
            "provider_attestation_digest": self.provider_digest,
            "model": "gpt-test",
            "sdk_version": "1.0",
            "corpus_version": "2026-07",
            "clock": clock or (lambda: 0.0),
        }
        values.update(overrides)
        return VectorReadinessService(SimpleNamespace(vector_stores=SimpleNamespace(files=self.files)), **values)

    @staticmethod
    def _page(rows, has_more=False, last_id=None):
        return {"data": rows, "has_more": has_more, "last_id": last_id}

    @staticmethod
    def _row(identifier, status="completed"):
        return {"file_id": identifier, "status": status}

    def test_paginates_at_100_and_returns_only_safe_inventory(self):
        service = self._service([
            self._page([self._row("file_private_one")], True, "cursor_private"),
            self._page([self._row("file_private_two")]),
        ])
        inventory = service()
        self.assertTrue(inventory["ready"])
        self.assertEqual(self.files.calls, [
            {"vector_store_id": "vs_private", "limit": VECTOR_LIST_PAGE_SIZE, "timeout": 5.0},
            {
                "vector_store_id": "vs_private",
                "limit": VECTOR_LIST_PAGE_SIZE,
                "timeout": 5.0,
                "after": "cursor_private",
            },
        ])
        self.assertEqual(inventory["count"], 2)
        self.assertNotIn("file_private", str(inventory))
        self.assertNotIn("vs_private", str(inventory))

    def test_rejects_more_than_two_pages_cursor_or_duplicate_drift(self):
        cases = [
            [
                self._page([self._row("file_private_one")], True, "first"),
                self._page([self._row("file_private_two")], True, "second"),
            ],
            [
                self._page([self._row("file_private_one")], True, "same"),
                self._page([self._row("file_private_two")], True, "same"),
            ],
            [
                self._page([self._row("file_private_one")], True, "first"),
                self._page([self._row("file_private_one")]),
            ],
        ]
        for pages in cases:
            with self.subTest(pages=pages):
                self.assertFalse(self._service(pages)()["ready"])

    def test_rejects_every_noncompleted_state_and_attested_inventory_mismatch(self):
        for state in ("in_progress", "failed", "cancelled", "unknown"):
            with self.subTest(state=state):
                self.assertFalse(self._service([
                    self._page([self._row("file_private_one"), self._row("file_private_two", state)])
                ])()["ready"])
        self.assertFalse(self._service([
            self._page([self._row("file_private_one"), self._row("unattested_private")])
        ])()["ready"])
        wrong_count = self._service(
            [self._page([self._row("file_private_one"), self._row("file_private_two")])],
            expected_inventory={
                "completed_file_count": 1,
                "files": [
                    {"file_id": "file_private_one", "filename": "guide.pdf", "digest": "c" * 64},
                    {"file_id": "file_private_two", "filename": "notice.pdf", "digest": "d" * 64},
                ],
            },
        )
        self.assertFalse(wrong_count()["ready"])

    def test_deadline_exception_and_shape_drift_fail_closed(self):
        ticks = iter((0.0, 0.0, 5.1))
        deadline = self._service(
            [self._page([self._row("file_private_one"), self._row("file_private_two")])],
            clock=lambda: next(ticks),
        )
        self.assertFalse(deadline()["ready"])
        for page in (RuntimeError("provider"), {"data": [], "has_more": "false"}, {"data": "bad", "has_more": False}):
            with self.subTest(page=page):
                self.assertFalse(self._service([page])()["ready"])
    def test_passes_decreasing_bounded_request_timeouts(self):
        clock = _FakeClock()
        service = self._service(
            [
                self._page([self._row("file_private_one")], True, "cursor_private"),
                self._page([self._row("file_private_two")]),
            ],
            clock=clock,
            advance=lambda: clock.advance(2.0),
        )

        self.assertTrue(service()["ready"])
        timeouts = [call["timeout"] for call in self.files.calls]
        self.assertEqual(timeouts, [5.0, 3.0])
        self.assertTrue(all(0 < timeout <= 5.0 for timeout in timeouts))

    def test_per_refresh_deadline_cap_bounds_transport_timeout(self):
        service = self._service(
            [self._page([self._row("file_private_one"), self._row("file_private_two")])]
        )

        self.assertTrue(service(deadline_seconds=2.0)["ready"])
        self.assertEqual(self.files.calls[0]["timeout"], 2.0)

    def test_shared_remaining_budget_prevents_rebased_request(self):
        service = self._service(
            [self._page([self._row("file_private_one"), self._row("file_private_two")])]
        )

        result = service(
            deadline_seconds=5.0,
            remaining_seconds=lambda: 0.0,
        )

        self.assertFalse(result["ready"])
        self.assertEqual(self.files.calls, [])

    def test_does_not_start_request_after_deadline_exhaustion(self):
        clock = _FakeClock()
        service = self._service(
            [
                self._page([self._row("file_private_one")], True, "cursor_private"),
                self._page([self._row("file_private_two")]),
            ],
            clock=clock,
            advance=lambda: clock.advance(5.0),
        )

        self.assertFalse(service()["ready"])
        self.assertEqual(len(self.files.calls), 1)
        self.assertEqual(self.files.calls[0]["timeout"], 5.0)

    def test_provider_timeout_replaces_expired_ready_cache_with_unready(self):
        clock = _FakeClock()
        service = self._service(
            [
                self._page([self._row("file_private_one"), self._row("file_private_two")]),
                TimeoutError("provider timeout"),
            ],
            clock=clock,
        )

        self.assertTrue(service()["ready"])
        clock.advance(60.0)
        self.assertFalse(service()["ready"])
        self.assertFalse(service()["ready"])
        self.assertEqual(len(self.files.calls), 2)
        self.assertEqual(self.files.calls[1]["timeout"], 5.0)

    def test_positive_negative_ttl_key_invalidation_and_no_stale_ready(self):
        now = [0.0]
        clock = lambda: now[0]
        pages = [
            self._page([self._row("file_private_one"), self._row("file_private_two")]),
            self._page([self._row("file_private_one"), self._row("file_private_two")]),
            self._page([self._row("file_private_one"), self._row("file_private_two")]),
            self._page([self._row("file_private_one"), self._row("file_private_two")]),
        ]
        service = self._service(pages, clock=clock)
        self.assertTrue(service()["ready"])
        self.assertTrue(service()["ready"])
        self.assertEqual(len(self.files.calls), 1)
        now[0] = 60.0
        self.assertTrue(service()["ready"])
        self.assertEqual(len(self.files.calls), 2)
        service._model = "gpt-other"
        self.assertTrue(service()["ready"])
        self.assertEqual(len(self.files.calls), 3)
        service._provider_attestation_digest = "e" * 64
        self.assertTrue(service()["ready"])
        self.assertEqual(len(self.files.calls), 4)

        failed = self._service([RuntimeError("first"), RuntimeError("second")], clock=clock)
        self.assertFalse(failed()["ready"])
        self.assertFalse(failed()["ready"])
        self.assertEqual(len(self.files.calls), 1)
        now[0] += 15.0
        self.assertFalse(failed()["ready"])
        self.assertEqual(len(self.files.calls), 2)

        stale = self._service([
            self._page([self._row("file_private_one"), self._row("file_private_two")]),
            RuntimeError("refresh"),
        ], clock=clock)
        self.assertTrue(stale()["ready"])
        now[0] += 60.0
        self.assertFalse(stale()["ready"])

    def test_single_flight_successfully_coalesces_concurrent_callers(self):
        gate = threading.Event()
        service = self._service([
            self._page([self._row("file_private_one"), self._row("file_private_two")])
        ], gate=gate)
        results = []
        workers = [threading.Thread(target=lambda: results.append(service())) for _ in range(2)]
        for worker in workers:
            worker.start()
        self.assertTrue(self.files.entered.wait(timeout=1))
        gate.set()
        for worker in workers:
            worker.join(timeout=1)
        self.assertEqual(len(self.files.calls), 1)
        self.assertEqual([item["ready"] for item in results], [True, True])

    def test_single_flight_follower_times_out_with_short_shared_budget(self):
        gate = threading.Event()
        service = self._service([
            self._page([self._row("file_private_one"), self._row("file_private_two")])
        ], gate=gate)
        leader = threading.Thread(target=service)
        leader.start()
        self.assertTrue(self.files.entered.wait(timeout=1))
        result = []
        follower = threading.Thread(
            target=lambda: result.append(service(remaining_seconds=lambda: 0.001))
        )
        follower.start()
        follower.join(timeout=1)
        self.assertFalse(follower.is_alive())
        self.assertEqual(result, [{"ready": False, "fresh": False, "count": 0, "files": []}])
        gate.set()
        leader.join(timeout=1)
        self.assertEqual(len(self.files.calls), 1)

    def test_single_flight_wake_does_not_reset_local_deadline(self):
        clock = _FakeClock()
        gate = threading.Event()
        service = self._service(
            [self._page([self._row("file_private_one"), self._row("file_private_two")])],
            clock=clock,
            gate=gate,
            advance=lambda: clock.advance(1.0),
        )
        leader = threading.Thread(target=service)
        leader.start()
        self.assertTrue(self.files.entered.wait(timeout=1))
        result = []
        follower = threading.Thread(
            target=lambda: result.append(service(deadline_seconds=0.5))
        )
        follower.start()
        gate.set()
        leader.join(timeout=1)
        follower.join(timeout=1)
        self.assertEqual([item["ready"] for item in result], [False])
        self.assertEqual(len(self.files.calls), 1)

    def test_attestation_expiry_during_refresh_never_returns_ready(self):
        clock = _FakeClock()
        wall_clock = [dt.datetime(2026, 7, 15, tzinfo=dt.timezone.utc)]
        service = self._service(
            [self._page([self._row("file_private_one"), self._row("file_private_two")])],
            clock=clock,
            attestation_expires_at=wall_clock[0] + dt.timedelta(seconds=1),
            wall_clock=lambda: wall_clock[0],
            advance=lambda: wall_clock.__setitem__(0, wall_clock[0] + dt.timedelta(seconds=1)),
        )
        self.assertFalse(service()["ready"])
        self.assertFalse(service()["ready"])
        self.assertEqual(len(self.files.calls), 1)

class FileEvidenceAdmissionTest(unittest.TestCase):
    scope = "00112233445566778899aabb"

    def _output(self, annotations, results) -> list[dict]:
        return [
            {"type": "message", "content": [{"type": "output_text", "annotations": annotations}]},
            {"type": "file_search_call", "status": "completed", "results": results},
        ]

    def _inventory(self) -> dict:
        return {"ready": True, "fresh": True, "files": [{"filename": "guide.pdf"}]}

    def _annotation(self, provider_index=999) -> dict:
        return {
            "type": "file_citation",
            "filename": "guide.pdf",
            "file_id": "file_provider_private",
            "index": provider_index,
        }

    def _result(self) -> dict:
        return {"filename": "guide.pdf", "file_id": "file_provider_private"}

    def test_uses_annotation_ordinal_not_provider_index_and_hides_private_ids(self) -> None:
        admitted = admit_file_citations(
            "근거",
            [{"source_scope": "file", "file_refs": [0]}],
            self._output([self._annotation(987)], [self._result()]),
            self.scope,
            self._inventory(),
        )
        self.assertEqual(
            admitted,
            [
                {
                    "evidence_id": "file:00112233445566778899aabb:1:0",
                    "type": "file",
                    "title": "guide.pdf",
                    "claim_ordinal": 0,
                }
            ],
        )
        self.assertNotIn("file_provider_private", str(admitted))

    def test_ignores_unused_top_k_result_but_rejects_global_binding_defects(self) -> None:
        claims = [{"source_scope": "file", "file_refs": [0]}]
        valid = admit_file_citations(
            "근거",
            claims,
            self._output(
                [self._annotation()],
                [self._result(), {"filename": "other.pdf", "file_id": "unused"}],
            ),
            self.scope,
            self._inventory(),
        )
        self.assertIsNotNone(valid)
        orphan = self._output([self._annotation(), self._annotation("second")], [self._result()])
        self.assertIsNone(admit_file_citations("근거", claims, orphan, self.scope, self._inventory()))
        duplicate = self._output([self._annotation(), self._annotation("second")], [self._result()])
        self.assertIsNone(
            admit_file_citations(
                "근거",
                [{"source_scope": "file", "file_refs": [0, 1]}],
                duplicate,
                self.scope,
                self._inventory(),
            )
        )
        self.assertIsNone(
            admit_file_citations(
                "근거",
                [{"source_scope": "file", "file_refs": [1]}],
                self._output([self._annotation()], [self._result()]),
                self.scope,
                self._inventory(),
            )
        )
        self.assertIsNone(
            admit_file_citations(
                "근거",
                claims,
                self._output([self._annotation()], [{"filename": "wrong.pdf", "file_id": "file_provider_private"}]),
                self.scope,
                self._inventory(),
            )
        )

    def test_rejects_stale_inventory_noncanonical_name_and_bounds(self) -> None:
        claims = [{"source_scope": "file", "file_refs": [0]}]
        output = self._output([self._annotation()], [self._result()])
        self.assertIsNone(
            admit_file_citations(
                "근거", claims, output, self.scope, {"ready": True, "fresh": False, "files": [{"filename": "guide.pdf"}]}
            )
        )
        output[0]["content"][0]["annotations"][0]["filename"] = "folder/guide.pdf"
        self.assertIsNone(admit_file_citations("근거", claims, output, self.scope, self._inventory()))
        oversized = self._output([self._annotation()], [self._result()] * (MAX_FILE_RESULTS_PER_CALL + 1))
        self.assertIsNone(admit_file_citations("근거", claims, oversized, self.scope, self._inventory()))

if __name__ == "__main__":
    unittest.main()
