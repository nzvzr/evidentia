"""M2 — the authenticated multipart upload API, feature-flag contract,
duplicate/version semantics, limits/quotas, and the safe response surface.

Everything here drives the real FastAPI app through the TestClient. The
tenant-corpus flag is toggled by mutating the cached Settings instance
(monkeypatch restores it), which is exactly what every handler reads.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.ingestion.worker import IngestionWorker
from app.models.db_models import (
    Document,
    DocumentBlob,
    DocumentSection,
    DocumentVersion,
    IngestionJob,
)

MD_BODY = b"# Policy\n\nIntro paragraph.\n\n## Controls\n\nEncrypt everything at rest.\n"
TXT_BODY = b"1. Scope\n\nAll production systems.\n\n2. Controls\n\nKeys rotate quarterly.\n"


@pytest.fixture
def corpus_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "evidentia_tenant_corpus_enabled", True)


def upload(account, body: bytes = MD_BODY, name: str = "policy.md", content_type: str = "text/markdown", url: str = "/api/documents/upload"):
    return account.post(url, files={"file": (name, body, content_type)})


def drain_jobs(session_factory) -> None:
    worker = IngestionWorker(session_factory, poll_seconds=0.01, max_attempts=3)
    while worker.process_one():
        pass


# --------------------------------------------------------------------------- #
# feature flag contract
# --------------------------------------------------------------------------- #


class TestFlagOff:
    def test_upload_returns_stable_disabled_response(self, alice):
        res = upload(alice)
        assert res.status_code == 403
        assert res.json()["code"] == "tenant_corpus_disabled"

    def test_new_version_and_retry_disabled(self, alice):
        res = alice.post("/api/documents/some-id/versions", files={"file": ("a.md", MD_BODY)})
        assert res.status_code == 403
        assert res.json()["code"] == "tenant_corpus_disabled"
        res = alice.post("/api/documents/some-id/retry")
        assert res.status_code == 403
        assert res.json()["code"] == "tenant_corpus_disabled"

    def test_list_response_shape_unchanged(self, alice):
        res = alice.get("/api/documents")
        assert res.status_code == 200
        assert set(res.json().keys()) == {"documents"}  # no tenantCorpus key

    def test_json_create_shape_unchanged_and_no_ingestion_rows(self, alice, db_session):
        res = alice.post("/api/documents", json={"title": "Doc", "contentText": "## A\nBody."})
        assert res.status_code == 201
        assert set(res.json().keys()) == {
            "id", "companyId", "title", "slug", "type", "category", "metadata", "createdAt",
        }
        assert db_session.execute(select(DocumentVersion)).scalars().all() == []
        assert db_session.execute(select(IngestionJob)).scalars().all() == []


class TestFlagOn:
    def test_list_exposes_upload_config(self, alice, corpus_on):
        res = alice.get("/api/documents")
        body = res.json()
        assert body["tenantCorpus"]["enabled"] is True
        assert body["tenantCorpus"]["acceptedExtensions"] == [".md", ".txt"]
        assert body["tenantCorpus"]["maxFileBytes"] > 0

    def test_json_create_routes_through_ingestion(self, alice, corpus_on, db_session):
        res = alice.post("/api/documents", json={"title": "Doc", "type": "MD", "contentText": "## A\nBody."})
        assert res.status_code == 201
        body = res.json()
        assert body["ingestion"]["stage"] == "pending"
        version = db_session.execute(select(DocumentVersion)).scalar_one()
        assert version.status == "pending"
        assert db_session.execute(select(IngestionJob)).scalar_one().state == "queued"


# --------------------------------------------------------------------------- #
# valid uploads + processing visibility
# --------------------------------------------------------------------------- #


class TestValidUploads:
    def test_markdown_upload_202_and_processing(self, alice, corpus_on, session_factory, db_session):
        res = upload(alice)
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["detectedFormat"] == "markdown"
        assert body["filename"] == "policy.md"
        assert body["byteSize"] == len(MD_BODY)
        assert body["versionNo"] == 1
        assert body["stage"] == "pending"
        assert body["duplicate"] is False and body["noop"] is False

        # No storage internals anywhere in the response.
        dump = json.dumps(body)
        assert "storage_key" not in dump and "db:" not in dump
        assert "Traceback" not in dump
        assert set(body.keys()) == {
            "documentId", "versionId", "versionNo", "filename", "detectedFormat",
            "byteSize", "status", "stage", "createdAt", "duplicate", "noop", "retried",
        }

        drain_jobs(session_factory)

        listed = alice.get("/api/documents").json()["documents"]
        mine = [d for d in listed if d.get("companyId")]
        assert len(mine) == 1
        ing = mine[0]["ingestion"]
        assert ing["stage"] == "ready"
        assert ing["status"] == "ready"
        assert ing["sectionCount"] == 2
        assert ing["errorCode"] is None
        # sections/citation internals never leak through the API
        assert "citation" not in json.dumps(mine[0]).lower()

    def test_txt_upload(self, alice, corpus_on, session_factory):
        res = upload(alice, TXT_BODY, "notes.txt", "text/plain")
        assert res.status_code == 202
        assert res.json()["detectedFormat"] == "text"
        drain_jobs(session_factory)
        doc = alice.get(f"/api/documents/{res.json()['documentId']}").json()
        assert doc["ingestion"]["stage"] == "ready"

    def test_document_detail_includes_ingestion(self, alice, corpus_on):
        doc_id = upload(alice).json()["documentId"]
        res = alice.get(f"/api/documents/{doc_id}")
        assert res.status_code == 200
        assert res.json()["ingestion"]["stage"] == "pending"


# --------------------------------------------------------------------------- #
# validation and typed rejections
# --------------------------------------------------------------------------- #


class TestValidation:
    def test_unsupported_extension(self, alice, corpus_on):
        res = upload(alice, b"MZ binary", "tool.exe", "application/octet-stream")
        assert res.status_code == 415
        assert res.json()["code"] == "unsupported_extension"

    def test_unsupported_detected_type_binary_magic(self, alice, corpus_on):
        res = upload(alice, b"%PDF-1.7 not really text", "report.md", "text/markdown")
        assert res.status_code == 415
        assert res.json()["code"] == "unsupported_type"

    def test_declared_detected_mismatch(self, alice, corpus_on):
        res = upload(alice, MD_BODY, "policy.md", "application/pdf")
        assert res.status_code == 415
        assert res.json()["code"] == "type_mismatch"

    def test_invalid_encoding(self, alice, corpus_on):
        res = upload(alice, b"\xff\xfe\x00broken", "notes.txt", "text/plain")
        assert res.status_code == 400
        assert res.json()["code"] == "invalid_encoding"

    def test_empty_file(self, alice, corpus_on):
        res = upload(alice, b"", "empty.md")
        assert res.status_code == 400
        assert res.json()["code"] == "empty_file"
        res = upload(alice, b"   \n \n", "blank.txt", "text/plain")
        assert res.status_code == 400
        assert res.json()["code"] == "empty_file"

    def test_oversized_file_while_streaming(self, alice, corpus_on, monkeypatch):
        monkeypatch.setattr(get_settings(), "evidentia_upload_max_file_bytes", 64)
        res = upload(alice, b"# T\n\n" + b"x" * 200, "big.md")
        assert res.status_code == 413
        assert res.json()["code"] == "file_too_large"

    def test_oversized_request_body(self, alice, corpus_on, monkeypatch):
        # Route body cap = max(body cap, file cap + 64 KiB overhead).
        monkeypatch.setattr(get_settings(), "evidentia_upload_max_file_bytes", 1024)
        oversized = b"y" * (512 * 1024 + 70 * 1024)
        res = upload(alice, oversized, "big.md")
        assert res.status_code == 413
        assert res.json()["code"] == "payload_too_large"

    def test_extracted_char_overflow(self, alice, corpus_on, monkeypatch):
        monkeypatch.setattr(get_settings(), "evidentia_max_extracted_chars", 50)
        res = upload(alice, b"# T\n\n" + b"a" * 100, "long.md")
        assert res.status_code == 413
        assert res.json()["code"] == "extraction_too_large"

    def test_filename_sanitization(self, alice, corpus_on):
        # Path components and leading dots are stripped server-side; the safe
        # display name survives. (Control characters are covered by the unit
        # test below because HTTP clients percent-encode them in transit.)
        res = upload(alice, MD_BODY, "../nested/..strange name.md", "text/markdown")
        assert res.status_code == 202
        assert res.json()["filename"] == "strange name.md"

    def test_sanitize_filename_unit(self):
        from app.services.document_upload import sanitize_filename

        assert sanitize_filename("..\\..\\evil\x01\x7f.md") == "evil.md"
        assert sanitize_filename("../../etc/passwd") == "passwd"
        assert sanitize_filename("  .hidden.md ") == "hidden.md"
        assert sanitize_filename("") == "document.txt"
        assert len(sanitize_filename("a" * 500 + ".md")) <= 200

    def test_path_traversal_filename_rejected(self, alice, corpus_on):
        res = upload(alice, MD_BODY, "../../etc/passwd", "text/plain")
        assert res.status_code == 415  # sanitized to "passwd": no allowed extension
        assert res.json()["code"] == "unsupported_extension"

    def test_two_files_rejected(self, alice, corpus_on):
        res = alice.post(
            "/api/documents/upload",
            files=[
                ("file", ("a.md", MD_BODY, "text/markdown")),
                ("file2", ("b.md", MD_BODY, "text/markdown")),
            ],
        )
        assert res.status_code == 400
        assert res.json()["code"] == "too_many_files"

    def test_missing_file(self, alice, corpus_on):
        res = alice.post("/api/documents/upload", data={"note": "no file"})
        assert res.status_code == 400
        assert res.json()["code"] == "missing_file"

    def test_unauthenticated_upload_is_401(self, client, corpus_on):
        res = client.post("/api/documents/upload", files={"file": ("a.md", MD_BODY)})
        assert res.status_code == 401


# --------------------------------------------------------------------------- #
# duplicate / version semantics
# --------------------------------------------------------------------------- #


class TestDuplicateAndVersions:
    def test_duplicate_upload_is_explicit_and_stores_nothing(self, alice, corpus_on, db_session):
        first = upload(alice)
        assert first.status_code == 202
        second = upload(alice, MD_BODY, "renamed-copy.md")
        assert second.status_code == 200
        body = second.json()
        assert body["duplicate"] is True
        assert body["documentId"] == first.json()["documentId"]
        assert body["versionId"] == first.json()["versionId"]

        assert len(db_session.execute(select(Document)).scalars().all()) == 1
        assert len(db_session.execute(select(DocumentVersion)).scalars().all()) == 1
        assert len(db_session.execute(select(DocumentBlob)).scalars().all()) == 1
        assert len(db_session.execute(select(IngestionJob)).scalars().all()) == 1

    def test_identical_new_version_is_noop(self, alice, corpus_on, session_factory, db_session):
        doc_id = upload(alice).json()["documentId"]
        drain_jobs(session_factory)
        res = alice.post(
            f"/api/documents/{doc_id}/versions",
            files={"file": ("policy.md", MD_BODY, "text/markdown")},
        )
        assert res.status_code == 200
        assert res.json()["noop"] is True
        assert res.json()["versionNo"] == 1
        assert len(db_session.execute(select(DocumentVersion)).scalars().all()) == 1
        # no second live job either
        live = [
            j for j in db_session.execute(select(IngestionJob)).scalars().all()
            if j.state in ("queued", "running")
        ]
        assert live == []

    def test_changed_bytes_create_version_2_keeping_v1(self, alice, corpus_on, session_factory, db_session):
        doc_id = upload(alice).json()["documentId"]
        drain_jobs(session_factory)
        v2_body = MD_BODY + b"\n## Appendix\n\nNew content in version two.\n"
        res = alice.post(
            f"/api/documents/{doc_id}/versions",
            files={"file": ("policy.md", v2_body, "text/markdown")},
        )
        assert res.status_code == 202
        assert res.json()["versionNo"] == 2
        drain_jobs(session_factory)

        versions = db_session.execute(
            select(DocumentVersion).order_by(DocumentVersion.version_no)
        ).scalars().all()
        assert [v.version_no for v in versions] == [1, 2]
        assert all(v.status == "ready" for v in versions)
        # v1 sections remain immutable alongside v2's
        v1_sections = db_session.execute(
            select(DocumentSection).where(DocumentSection.version_id == versions[0].id)
        ).scalars().all()
        assert len(v1_sections) == 2
        doc = db_session.execute(select(Document)).scalar_one()
        assert doc.current_version_id == versions[1].id

    def test_failed_new_version_keeps_previous_current(self, alice, corpus_on, session_factory, db_session, monkeypatch):
        doc_id = upload(alice).json()["documentId"]
        drain_jobs(session_factory)
        v1 = db_session.execute(select(DocumentVersion)).scalar_one()

        # v2 whose extraction overflows the char cap -> typed terminal failure
        monkeypatch.setattr(get_settings(), "evidentia_max_extracted_chars", 10_000)
        big = b"# T\n\n" + b"z" * 20_000
        # upload must pass the API check, so raise the cap for the request...
        monkeypatch.setattr(get_settings(), "evidentia_max_extracted_chars", 50_000)
        res = alice.post(
            f"/api/documents/{doc_id}/versions", files={"file": ("policy.md", big, "text/markdown")}
        )
        assert res.status_code == 202
        # ...then lower it before the worker runs (simulates a processing-time failure)
        monkeypatch.setattr(get_settings(), "evidentia_max_extracted_chars", 10_000)
        drain_jobs(session_factory)

        db_session.expire_all()
        doc = db_session.execute(select(Document)).scalar_one()
        assert doc.current_version_id == v1.id  # previous working version intact
        assert doc.status == "ready"
        v2 = db_session.execute(
            select(DocumentVersion).where(DocumentVersion.version_no == 2)
        ).scalar_one()
        assert v2.status == "failed"
        assert v2.error_code == "extraction_too_large"

        listed = alice.get("/api/documents").json()["documents"]
        ing = [d for d in listed if d.get("companyId")][0]["ingestion"]
        assert ing["stage"] == "failed"
        assert ing["errorCode"] == "extraction_too_large"

    def test_retry_failed_version(self, alice, corpus_on, session_factory, db_session, monkeypatch):
        monkeypatch.setattr(get_settings(), "evidentia_max_extracted_chars", 40)
        res = upload(alice, b"# T\n\n" + b"q" * 30 + b" more text beyond the processing cap", "r.md")
        # passes API validation? 30+notes > 40 chars -> rejected at API. Use a
        # processing-time failure instead: valid at upload, fails in worker.
        if res.status_code != 202:
            monkeypatch.setattr(get_settings(), "evidentia_max_extracted_chars", 200)
            res = upload(alice, b"# T\n\n" + b"q" * 100, "r.md")
            assert res.status_code == 202
            monkeypatch.setattr(get_settings(), "evidentia_max_extracted_chars", 40)
        doc_id = res.json()["documentId"]
        drain_jobs(session_factory)

        v = db_session.execute(select(DocumentVersion)).scalar_one()
        assert v.status == "failed"

        # fix the cap and retry: same version, new job, sections appear once
        monkeypatch.setattr(get_settings(), "evidentia_max_extracted_chars", 1_000_000)
        retry = alice.post(f"/api/documents/{doc_id}/retry")
        assert retry.status_code == 202
        assert retry.json()["retried"] is True
        drain_jobs(session_factory)

        db_session.expire_all()
        versions = db_session.execute(select(DocumentVersion)).scalars().all()
        assert len(versions) == 1  # no duplicate version
        assert versions[0].status == "ready"
        blobs = db_session.execute(select(DocumentBlob)).scalars().all()
        assert len(blobs) == 1  # no duplicate blob

    def test_retry_requires_failed_version(self, alice, corpus_on):
        doc_id = upload(alice).json()["documentId"]
        res = alice.post(f"/api/documents/{doc_id}/retry")
        assert res.status_code == 409
        assert res.json()["code"] == "version_not_failed"


# --------------------------------------------------------------------------- #
# tenancy
# --------------------------------------------------------------------------- #


class TestTenancy:
    def test_cross_tenant_document_version_and_retry_are_404(self, alice, bob, corpus_on):
        doc_id = upload(alice).json()["documentId"]
        assert bob.get(f"/api/documents/{doc_id}").status_code == 404
        res = bob.post(
            f"/api/documents/{doc_id}/versions",
            files={"file": ("x.md", MD_BODY, "text/markdown")},
        )
        assert res.status_code == 404
        assert bob.post(f"/api/documents/{doc_id}/retry").status_code == 404

    def test_identical_bytes_in_other_tenant_do_not_leak(self, alice, bob, corpus_on, db_session):
        """Cross-tenant dedupe must not exist: Bob uploading Alice's exact
        bytes gets his own document and learns nothing about hers."""
        alice_doc = upload(alice).json()["documentId"]
        res = upload(bob)
        assert res.status_code == 202  # not a duplicate: tenant-scoped dedupe
        assert res.json()["duplicate"] is False
        assert res.json()["documentId"] != alice_doc
        docs = db_session.execute(select(Document)).scalars().all()
        assert len(docs) == 2
        blobs = db_session.execute(select(DocumentBlob)).scalars().all()
        assert len(blobs) == 2  # no cross-tenant physical dedupe in M2

    def test_tenant_listing_never_shows_other_tenants(self, alice, bob, corpus_on):
        upload(alice)
        listed = bob.get("/api/documents").json()["documents"]
        assert all(not d.get("companyId") for d in listed)  # demo fallback only


# --------------------------------------------------------------------------- #
# rate limits and quotas
# --------------------------------------------------------------------------- #


class TestLimits:
    def test_per_user_rate_limit(self, alice, corpus_on, monkeypatch):
        monkeypatch.setattr(get_settings(), "rl_upload_user_limit", 2)
        assert upload(alice, MD_BODY, "a.md").status_code == 202
        assert upload(alice, MD_BODY + b"b", "b.md").status_code == 202
        res = upload(alice, MD_BODY + b"c", "c.md")
        assert res.status_code == 429
        assert res.json()["code"] == "rate_limited"
        assert "Retry-After" in res.headers

    def test_per_tenant_rate_limit(self, alice, corpus_on, monkeypatch):
        monkeypatch.setattr(get_settings(), "rl_upload_user_limit", 100)
        monkeypatch.setattr(get_settings(), "rl_upload_tenant_limit", 2)
        assert upload(alice, MD_BODY, "a.md").status_code == 202
        assert upload(alice, MD_BODY + b"b", "b.md").status_code == 202
        assert upload(alice, MD_BODY + b"c", "c.md").status_code == 429

    def test_document_count_quota(self, alice, corpus_on, monkeypatch):
        monkeypatch.setattr(get_settings(), "evidentia_tenant_max_documents", 1)
        assert upload(alice, MD_BODY, "a.md").status_code == 202
        res = upload(alice, MD_BODY + b"different", "b.md")
        assert res.status_code == 403
        assert res.json()["code"] == "document_quota_exceeded"

    def test_stored_bytes_quota(self, alice, corpus_on, monkeypatch):
        monkeypatch.setattr(get_settings(), "evidentia_tenant_max_total_bytes", 10)
        res = upload(alice)
        assert res.status_code == 403
        assert res.json()["code"] == "storage_quota_exceeded"

    def test_quota_is_per_tenant(self, alice, bob, corpus_on, monkeypatch):
        monkeypatch.setattr(get_settings(), "evidentia_tenant_max_documents", 1)
        assert upload(alice).status_code == 202
        assert upload(bob).status_code == 202  # Bob's tenant has its own budget


# --------------------------------------------------------------------------- #
# flag-on JSON create shares the multipart abuse bounds (review fix):
# same upload rate budgets, same company-row lock, same count/byte quotas,
# same typed codes — and a rejection leaves no row of any kind behind.
# --------------------------------------------------------------------------- #


def json_create(account, title: str = "Doc", text: str = "## A\nBody.", doc_type: str = "MD"):
    return account.post(
        "/api/documents", json={"title": title, "type": doc_type, "contentText": text}
    )


def count_rows(db_session) -> dict:
    return {
        "documents": len(db_session.execute(select(Document)).scalars().all()),
        "versions": len(db_session.execute(select(DocumentVersion)).scalars().all()),
        "blobs": len(db_session.execute(select(DocumentBlob)).scalars().all()),
        "jobs": len(db_session.execute(select(IngestionJob)).scalars().all()),
    }


class TestJsonCreateLimits:
    def test_document_count_quota_rejected_and_no_rows(self, alice, corpus_on, monkeypatch, db_session):
        monkeypatch.setattr(get_settings(), "evidentia_tenant_max_documents", 1)
        assert json_create(alice, title="First", text="## A\nOne.").status_code == 201
        before = count_rows(db_session)
        res = json_create(alice, title="Second", text="## B\nTwo.")
        assert res.status_code == 403
        assert res.json()["code"] == "document_quota_exceeded"
        db_session.expire_all()
        assert count_rows(db_session) == before  # the rejection wrote nothing

    def test_stored_byte_quota_rejected_and_no_rows(self, alice, corpus_on, monkeypatch, db_session):
        monkeypatch.setattr(get_settings(), "evidentia_tenant_max_total_bytes", 10)
        res = json_create(alice, text="x" * 50)
        assert res.status_code == 403
        assert res.json()["code"] == "storage_quota_exceeded"
        assert count_rows(db_session) == {"documents": 0, "versions": 0, "blobs": 0, "jobs": 0}

    def test_byte_quota_uses_actual_utf8_size(self, alice, corpus_on, monkeypatch):
        text = "é" * 20  # 20 characters, 40 UTF-8 bytes
        monkeypatch.setattr(get_settings(), "evidentia_tenant_max_total_bytes", 39)
        res = json_create(alice, text=text)
        assert res.status_code == 403
        assert res.json()["code"] == "storage_quota_exceeded"
        monkeypatch.setattr(get_settings(), "evidentia_tenant_max_total_bytes", 40)
        assert json_create(alice, text=text).status_code == 201

    def test_json_create_consumes_the_upload_rate_budget(self, alice, corpus_on, monkeypatch, db_session):
        """One budget, not two: multipart uploads and JSON creates draw from the
        same per-user upload window, and a throttled create writes nothing."""
        monkeypatch.setattr(get_settings(), "rl_upload_user_limit", 2)
        assert upload(alice).status_code == 202
        assert json_create(alice, title="Second", text="## B\nTwo.").status_code == 201
        before = count_rows(db_session)
        res = json_create(alice, title="Third", text="## C\nThree.")
        assert res.status_code == 429
        assert res.json()["code"] == "rate_limited"
        assert "Retry-After" in res.headers
        db_session.expire_all()
        assert count_rows(db_session) == before

    def test_per_tenant_rate_budget_applies_to_json_create(self, alice, corpus_on, monkeypatch):
        monkeypatch.setattr(get_settings(), "rl_upload_user_limit", 100)
        monkeypatch.setattr(get_settings(), "rl_upload_tenant_limit", 1)
        assert json_create(alice, title="First", text="one").status_code == 201
        res = json_create(alice, title="Second", text="two")
        assert res.status_code == 429
        assert res.json()["code"] == "rate_limited"

    def test_successful_json_create_rows_and_response_shape(self, alice, corpus_on, db_session):
        res = json_create(alice)
        assert res.status_code == 201
        body = res.json()
        assert set(body.keys()) == {
            "id", "companyId", "title", "slug", "type", "category", "metadata",
            "createdAt", "ingestion",
        }
        assert body["ingestion"]["stage"] == "pending"
        assert count_rows(db_session) == {"documents": 1, "versions": 1, "blobs": 1, "jobs": 1}
        version = db_session.execute(select(DocumentVersion)).scalar_one()
        assert version.version_no == 1 and version.status == "pending"
        assert db_session.execute(select(IngestionJob)).scalar_one().state == "queued"

    def test_flag_off_json_create_keeps_legacy_behavior(self, alice, monkeypatch, db_session):
        """With the corpus flag off the JSON path must stay byte-for-byte
        pre-M2: no upload rate budget, no quotas, no ingestion rows — even
        with every limit set to zero."""
        monkeypatch.setattr(get_settings(), "rl_upload_user_limit", 0)
        monkeypatch.setattr(get_settings(), "rl_upload_tenant_limit", 0)
        monkeypatch.setattr(get_settings(), "evidentia_tenant_max_documents", 0)
        monkeypatch.setattr(get_settings(), "evidentia_tenant_max_total_bytes", 0)
        for i in range(3):
            res = alice.post(
                "/api/documents", json={"title": f"Legacy {i}", "contentText": "## A\nBody."}
            )
            assert res.status_code == 201
            assert set(res.json().keys()) == {
                "id", "companyId", "title", "slug", "type", "category", "metadata", "createdAt",
            }
        assert count_rows(db_session) == {"documents": 3, "versions": 0, "blobs": 0, "jobs": 0}


# --------------------------------------------------------------------------- #
# generation isolation (tenant sections never reach reports before M4)
# --------------------------------------------------------------------------- #


class TestGenerationIsolation:
    def test_generation_still_uses_demo_corpus_only(self, alice, corpus_on, session_factory):
        body = (
            b"# Quantum Flux Policy\n\n## Chrono Controls\n\n"
            b"The zorblax-7 flux capacitor must be recalibrated weekly by the chrono team.\n"
        )
        res = upload(alice, body, "quantum.md")
        doc_id = res.json()["documentId"]
        drain_jobs(session_factory)

        gen = alice.post(
            "/api/generate-workflow",
            json={"market": "EMEA", "persona": "Support Agent", "selectedDocumentIds": [doc_id]},
        )
        assert gen.status_code == 200
        report = gen.json()
        dump = json.dumps(report)
        # No tenant content and no tenant/demo mixing: the unknown tenant id
        # falls back to the demo corpus, and nothing from the upload leaks in.
        assert "zorblax-7" not in dump
        assert "Quantum Flux" not in dump
        demo_titles = (
            "Security & Compliance Whitepaper",
            "SLA & Uptime Commitment",
            "Deployment & Migration Guide",
            "Customer Onboarding Handbook",
        )
        assert report["citations"], "expected demo-corpus citations"
        for citation in report["citations"]:
            assert citation["source"].startswith(demo_titles)
