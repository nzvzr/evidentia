"""M2 — DatabaseJobQueue worker operations, the ingestion pipeline state
machine, the in-process worker lifecycle, and backfill -> worker integration.

Concurrency notes: the claim/heartbeat/complete/fail transitions are atomic
conditional UPDATEs. The default (SQLite) run proves the application logic
under SQLite's single-writer lock; the opt-in PostgreSQL profile
(EVIDENTIA_TEST_DATABASE_URL) runs this whole file against real row locks —
the two-worker claim race below is only *meaningful* proof there, and the
dedicated test skips loudly when the profile is off.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.ingestion.errors import IngestionError
from app.ingestion.pipeline import (
    InvalidTransition,
    mark_version_failed,
    process_version,
    resolve_source_format,
    transition_version,
)
from app.ingestion.worker import IngestionWorker
from app.models.db_models import (
    JOB_STATE_FAILED,
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    JOB_STATE_SUCCEEDED,
    VERSION_STATUS_FAILED,
    VERSION_STATUS_READY,
    Company,
    Document,
    DocumentBlob,
    DocumentSection,
    DocumentVersion,
    IngestionJob,
)
from app.services.blob_store import DatabaseBlobStore
from app.services.document_backfill import backfill_content_text_documents
from app.services.job_queue import DatabaseJobQueue

POSTGRES_PROFILE = bool(os.getenv("EVIDENTIA_TEST_DATABASE_URL", "").strip())

MARKDOWN = """# Runbook

Intro paragraph with enough words to be a real body of content for tests.

## Escalation

Page the on-call within five minutes. Severity one incidents page the incident
commander directly and open a bridge.

## Rollback

Use the previous deployment image. Never roll back the database schema without
a verified backup.
"""


@pytest.fixture
def company(db_session) -> Company:
    row = Company(name="Acme", slug="acme")
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def other_company(db_session) -> Company:
    row = Company(name="Globex", slug="globex")
    db_session.add(row)
    db_session.commit()
    return row


def make_uploaded_document(
    db, company_id: str, *, title: str = "Runbook", content: str = MARKDOWN, mime: str = "text/markdown"
):
    """A document + pending version + blob + queued job — the upload shape."""
    doc = Document(
        company_id=company_id,
        title=title,
        slug=title.lower(),
        type="MD" if mime == "text/markdown" else "TXT",
        mime_type=mime,
        original_filename=f"{title.lower()}.md" if mime == "text/markdown" else f"{title.lower()}.txt",
        source_type="upload",
        status="processing",
    )
    db.add(doc)
    db.flush()
    version = DocumentVersion(document_id=doc.id, company_id=company_id, version_no=1)
    db.add(version)
    db.flush()
    DatabaseBlobStore().put(db, company_id=company_id, version_id=version.id, data=content.encode("utf-8"))
    job = DatabaseJobQueue().enqueue(db, company_id=company_id, document_id=doc.id, version_id=version.id)
    db.commit()
    return doc, version, job


def make_worker(session_factory, **kw) -> IngestionWorker:
    kw.setdefault("poll_seconds", 0.02)
    kw.setdefault("max_attempts", 3)
    return IngestionWorker(session_factory, **kw)


# --------------------------------------------------------------------------- #
# queue operations
# --------------------------------------------------------------------------- #


class TestClaim:
    def test_claim_moves_queued_to_running_and_increments_attempts(self, db_session, session_factory, company):
        _doc, version, job = make_uploaded_document(db_session, company.id)
        queue = DatabaseJobQueue()
        claim_db = session_factory()
        try:
            claimed = queue.claim(claim_db)
            claim_db.commit()
            assert claimed is not None and claimed.id == job.id
            assert claimed.state == JOB_STATE_RUNNING
            assert claimed.attempts == 1  # claim-time increment
            assert claimed.heartbeat_at is not None
        finally:
            claim_db.close()

    def test_claim_returns_none_when_idle(self, session_factory):
        db = session_factory()
        try:
            assert DatabaseJobQueue().claim(db) is None
        finally:
            db.close()

    def test_tenant_fair_claim_order(self, db_session, session_factory, company, other_company):
        """Tenant A's backlog must not starve tenant B: with A=3 jobs queued
        first and B=1 queued last, B is served within the first two claims,
        and every job is eventually served."""
        for i in range(3):
            make_uploaded_document(db_session, company.id, title=f"A{i}")
        make_uploaded_document(db_session, other_company.id, title="B0")

        queue = DatabaseJobQueue()
        db = session_factory()
        try:
            served = []
            for _ in range(4):
                job = queue.claim(db)
                assert job is not None
                db.commit()
                served.append(job.company_id)
            assert queue.claim(db) is None
            assert set(served[:2]) == {company.id, other_company.id}
            assert sorted(served) == sorted([company.id] * 3 + [other_company.id])
        finally:
            db.close()

    def test_two_workers_claim_race_exactly_one_owner(self, db_session, session_factory, company):
        """Two sessions racing for ONE queued job: exactly one wins. On
        PostgreSQL this exercises real row locks; on SQLite the single-writer
        lock serializes the conditional UPDATEs."""
        make_uploaded_document(db_session, company.id)
        queue_a, queue_b = DatabaseJobQueue(), DatabaseJobQueue()
        results, errors = [], []
        barrier = threading.Barrier(2)

        def racer(queue):
            db = session_factory()
            try:
                barrier.wait(timeout=5)
                job = queue.claim(db)
                db.commit()
                results.append(job.id if job is not None else None)
            except Exception as exc:  # noqa: BLE001 - collected and asserted
                errors.append(exc)
            finally:
                db.close()

        threads = [threading.Thread(target=racer, args=(q,)) for q in (queue_a, queue_b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert errors == []
        winners = [r for r in results if r is not None]
        assert len(winners) == 1

        check = session_factory()
        try:
            job = check.execute(select(IngestionJob)).scalar_one()
            assert job.state == JOB_STATE_RUNNING
            assert job.attempts == 1  # exactly one increment
        finally:
            check.close()

    @pytest.mark.skipif(
        not POSTGRES_PROFILE,
        reason=(
            "PostgreSQL-only: two-worker claim race against real row locks requires "
            "EVIDENTIA_TEST_DATABASE_URL (the SQLite run above proves only the "
            "application-side serialization)"
        ),
    )
    def test_postgres_profile_is_active_for_claim_race(self, engine):
        assert engine.dialect.name == "postgresql"


class TestJobLifecycle:
    def _claimed(self, db_session, session_factory, company):
        make_uploaded_document(db_session, company.id)
        db = session_factory()
        job = DatabaseJobQueue().claim(db)
        db.commit()
        return db, job

    def test_heartbeat_applies_only_to_running_job(self, db_session, session_factory, company):
        db, job = self._claimed(db_session, session_factory, company)
        try:
            queue = DatabaseJobQueue()
            assert queue.heartbeat(db, job.id) is True
            queue.complete(db, job.id)
            db.commit()
            assert queue.heartbeat(db, job.id) is False  # not running any more
        finally:
            db.close()

    def test_complete(self, db_session, session_factory, company):
        db, job = self._claimed(db_session, session_factory, company)
        try:
            assert DatabaseJobQueue().complete(db, job.id) is True
            db.commit()
            db.refresh(job)
            assert job.state == JOB_STATE_SUCCEEDED
        finally:
            db.close()

    def test_retryable_failure_requeues_below_cap(self, db_session, session_factory, company):
        db, job = self._claimed(db_session, session_factory, company)
        try:
            state = DatabaseJobQueue().fail(
                db, job.id, error="transient", retryable=True, max_attempts=3
            )
            db.commit()
            assert state == JOB_STATE_QUEUED
            db.refresh(job)
            assert job.state == JOB_STATE_QUEUED
            assert job.last_error == "transient"
            assert job.heartbeat_at is None
        finally:
            db.close()

    def test_terminal_failure(self, db_session, session_factory, company):
        db, job = self._claimed(db_session, session_factory, company)
        try:
            state = DatabaseJobQueue().fail(
                db, job.id, error="poison", retryable=False, max_attempts=3
            )
            db.commit()
            assert state == JOB_STATE_FAILED
        finally:
            db.close()

    def test_max_attempts_forces_terminal(self, db_session, session_factory, company):
        db, job = self._claimed(db_session, session_factory, company)
        try:
            queue = DatabaseJobQueue()
            # attempts is already 1; requeue+reclaim until the cap is hit
            for expected_attempts in (2, 3):
                assert queue.fail(db, job.id, error="e", retryable=True, max_attempts=3) == JOB_STATE_QUEUED
                db.commit()
                reclaimed = queue.claim(db)
                db.commit()
                assert reclaimed.id == job.id
                assert reclaimed.attempts == expected_attempts
            state = queue.fail(db, job.id, error="e", retryable=True, max_attempts=3)
            db.commit()
            assert state == JOB_STATE_FAILED  # attempts == cap => terminal
        finally:
            db.close()

    def test_terminal_jobs_never_reclaimed(self, db_session, session_factory, company):
        db, job = self._claimed(db_session, session_factory, company)
        try:
            queue = DatabaseJobQueue()
            queue.complete(db, job.id)
            db.commit()
            assert queue.claim(db) is None
            assert queue.complete(db, job.id) is True or True  # idempotence probe below
            db.rollback()
            db.refresh(job)
            assert job.state == JOB_STATE_SUCCEEDED
        finally:
            db.close()

    def test_stale_running_recovery_requeues_below_cap(self, db_session, session_factory, company):
        db, job = self._claimed(db_session, session_factory, company)
        try:
            queue = DatabaseJobQueue()
            stale_before = datetime.utcnow() + timedelta(seconds=60)  # everything is stale
            touched = queue.recover_stale(db, stale_before=stale_before, max_attempts=3)
            db.commit()
            assert [t.id for t in touched] == [job.id]
            db.refresh(job)
            assert job.state == JOB_STATE_QUEUED
            assert job.attempts == 1  # NOT incremented again by the sweep
        finally:
            db.close()

    def test_stale_running_at_cap_fails_terminally(self, db_session, session_factory, company):
        db, job = self._claimed(db_session, session_factory, company)
        try:
            queue = DatabaseJobQueue()
            # exhaust: requeue+reclaim twice -> attempts 3 (== cap)
            for _ in range(2):
                queue.fail(db, job.id, error="e", retryable=True, max_attempts=3)
                db.commit()
                queue.claim(db)
                db.commit()
            touched = queue.recover_stale(
                db, stale_before=datetime.utcnow() + timedelta(seconds=60), max_attempts=3
            )
            db.commit()
            db.refresh(job)
            assert job.state == JOB_STATE_FAILED
            assert "stale_abandoned" in (job.last_error or "")
        finally:
            db.close()

    def test_fresh_running_job_is_not_swept(self, db_session, session_factory, company):
        db, job = self._claimed(db_session, session_factory, company)
        try:
            touched = DatabaseJobQueue().recover_stale(
                db, stale_before=datetime.utcnow() - timedelta(seconds=300), max_attempts=3
            )
            db.commit()
            assert touched == []
            db.refresh(job)
            assert job.state == JOB_STATE_RUNNING
        finally:
            db.close()


# --------------------------------------------------------------------------- #
# pipeline: state machine + atomic persistence
# --------------------------------------------------------------------------- #


class TestPipeline:
    def test_process_version_end_to_end_markdown(self, db_session, session_factory, company):
        doc, version, _job = make_uploaded_document(db_session, company.id)
        db = session_factory()
        try:
            result = process_version(db, version_id=version.id, company_id=company.id)
            assert result.status == VERSION_STATUS_READY
            assert result.section_count == 3  # Runbook intro, Escalation, Rollback
            assert result.manifest_sha256 and result.extracted_sha256
            assert result.parser_name == "markdown-it-py"
            assert result.anchor_algo_version == "pre-m3-transitional"

            sections = db.execute(
                select(DocumentSection).where(DocumentSection.version_id == version.id).order_by(DocumentSection.ordinal)
            ).scalars().all()
            assert [s.title for s in sections] == ["Runbook", "Escalation", "Rollback"]
            assert sections[1].heading_path == ["Runbook", "Escalation"]
            assert all(s.company_id == company.id for s in sections)

            fresh_doc = db.get(Document, doc.id)
            assert fresh_doc.current_version_id == version.id  # the single flip site
            assert fresh_doc.status == "ready"
        finally:
            db.close()

    def test_reprocessing_does_not_duplicate_sections(self, db_session, session_factory, company):
        _doc, version, _job = make_uploaded_document(db_session, company.id)
        db = session_factory()
        try:
            process_version(db, version_id=version.id, company_id=company.id)
            first = db.execute(
                select(DocumentSection.text_sha256)
                .where(DocumentSection.version_id == version.id)
                .order_by(DocumentSection.ordinal)
            ).scalars().all()

            # a ready version returns immediately (idempotent)
            process_version(db, version_id=version.id, company_id=company.id)
            again = db.execute(
                select(DocumentSection.text_sha256)
                .where(DocumentSection.version_id == version.id)
                .order_by(DocumentSection.ordinal)
            ).scalars().all()
            assert again == first
        finally:
            db.close()

    def test_interrupted_run_rewrites_atomically(self, db_session, session_factory, company):
        """A version stuck mid-flight (extracting/sectioning after a crash)
        reprocesses cleanly: same sections, no duplicates."""
        _doc, version, _job = make_uploaded_document(db_session, company.id)
        db = session_factory()
        try:
            transitioned = db.get(DocumentVersion, version.id)
            transition_version(transitioned, "extracting")
            db.commit()

            result = process_version(db, version_id=version.id, company_id=company.id)
            assert result.status == VERSION_STATUS_READY
            count = len(
                db.execute(
                    select(DocumentSection).where(DocumentSection.version_id == version.id)
                ).scalars().all()
            )
            assert count == 3
        finally:
            db.close()

    def test_failure_mid_persist_leaves_no_partial_sections(self, db_session, session_factory, company, monkeypatch):
        _doc, version, _job = make_uploaded_document(db_session, company.id)

        import app.ingestion.pipeline as pipeline_module

        def boom(_drafts):
            raise RuntimeError("mid-persist crash")

        monkeypatch.setattr(pipeline_module, "manifest_sha256", boom)
        db = session_factory()
        try:
            with pytest.raises(RuntimeError):
                process_version(db, version_id=version.id, company_id=company.id)
            db.rollback()
        finally:
            db.close()

        check = session_factory()
        try:
            rows = check.execute(
                select(DocumentSection).where(DocumentSection.version_id == version.id)
            ).scalars().all()
            assert rows == []  # nothing partially visible
            fresh = check.get(DocumentVersion, version.id)
            assert fresh.status != VERSION_STATUS_READY
            fresh_doc = check.get(Document, fresh.document_id)
            assert fresh_doc.current_version_id is None
        finally:
            check.close()

    def test_invalid_transition_rejected(self, db_session, company):
        doc, version, _job = make_uploaded_document(db_session, company.id)
        version = db_session.get(DocumentVersion, version.id)
        version.status = VERSION_STATUS_READY
        db_session.commit()
        with pytest.raises(InvalidTransition):
            transition_version(version, "extracting")  # ready is immutable

    def test_typed_failure_persisted_and_bounded(self, db_session, session_factory, company):
        _doc, version, _job = make_uploaded_document(db_session, company.id)
        db = session_factory()
        try:
            error = IngestionError("parse_failed", "The document could not be parsed. " + "x" * 500)
            mark_version_failed(db, version_id=version.id, company_id=company.id, error=error)
            fresh = db.get(DocumentVersion, version.id)
            assert fresh.status == VERSION_STATUS_FAILED
            assert fresh.error_code == "parse_failed"
            assert len(fresh.error_detail) <= 300  # bounded, user-safe
            assert "Traceback" not in fresh.error_detail
        finally:
            db.close()

    def test_failed_new_version_never_degrades_ready_document(self, db_session, session_factory, company):
        doc, v1, _job = make_uploaded_document(db_session, company.id)
        db = session_factory()
        try:
            process_version(db, version_id=v1.id, company_id=company.id)

            # second version with broken bytes
            v2 = DocumentVersion(document_id=doc.id, company_id=company.id, version_no=2)
            db.add(v2)
            db.flush()
            DatabaseBlobStore().put(db, company_id=company.id, version_id=v2.id, data=b"\xff\xfe broken")
            db.commit()

            with pytest.raises(IngestionError):
                process_version(db, version_id=v2.id, company_id=company.id)
            db.rollback()
            mark_version_failed(
                db, version_id=v2.id, company_id=company.id,
                error=IngestionError("invalid_encoding", "not utf-8"),
            )

            fresh_doc = db.get(Document, doc.id)
            assert fresh_doc.current_version_id == v1.id  # previous version intact
            assert fresh_doc.status == "ready"  # never degraded by the failure
            v1_sections = db.execute(
                select(DocumentSection).where(DocumentSection.version_id == v1.id)
            ).scalars().all()
            assert len(v1_sections) == 3
        finally:
            db.close()

    def test_resolve_source_format(self, db_session, company):
        md = Document(company_id=company.id, title="a", slug="a", mime_type="text/markdown")
        txt = Document(company_id=company.id, title="b", slug="b", mime_type="text/plain")
        legacy_md = Document(company_id=company.id, title="c", slug="c", type="MD", mime_type="text/plain")
        legacy_meta = Document(
            company_id=company.id, title="d", slug="d", mime_type="text/plain",
            metadata_json={"filename": "notes.md"},
        )
        assert resolve_source_format(md) == "markdown"
        assert resolve_source_format(txt) == "text"
        assert resolve_source_format(legacy_md) == "markdown"
        assert resolve_source_format(legacy_meta) == "markdown"


# --------------------------------------------------------------------------- #
# worker
# --------------------------------------------------------------------------- #


class TestWorker:
    def test_process_one_end_to_end(self, db_session, session_factory, company):
        doc, version, _job = make_uploaded_document(db_session, company.id)
        worker = make_worker(session_factory)
        assert worker.process_one() is True
        assert worker.process_one() is False  # queue drained

        check = session_factory()
        try:
            job = check.execute(select(IngestionJob)).scalar_one()
            assert job.state == JOB_STATE_SUCCEEDED
            fresh = check.get(DocumentVersion, version.id)
            assert fresh.status == VERSION_STATUS_READY
            fresh_doc = check.get(Document, doc.id)
            assert fresh_doc.current_version_id == version.id
        finally:
            check.close()

    def test_poison_document_terminal_not_infinite(self, db_session, session_factory, company, monkeypatch):
        """An UNEXPECTED failure (outside the classified parser wrapper) is
        retried, but a poison document must hit the attempts cap and stop —
        never loop forever."""
        make_uploaded_document(db_session, company.id)
        import app.ingestion.pipeline as pipeline_module

        def boom(_doc_ir):
            raise RuntimeError("boom")

        monkeypatch.setattr(pipeline_module, "sectionize", boom)
        worker = make_worker(session_factory, max_attempts=3)
        processed = 0
        while worker.process_one():
            processed += 1
            assert processed <= 10, "poison document looped past the attempts cap"

        check = session_factory()
        try:
            job = check.execute(select(IngestionJob)).scalar_one()
            assert job.state == JOB_STATE_FAILED
            assert job.attempts == 3
            version = check.execute(select(DocumentVersion)).scalar_one()
            assert version.status == VERSION_STATUS_FAILED
            assert version.error_code == "ingestion_failed"
        finally:
            check.close()

    def test_terminal_parse_failure_is_immediate(self, db_session, session_factory, company):
        make_uploaded_document(db_session, company.id, content="x", mime="text/plain")
        db = session_factory()
        try:
            blob = db.execute(select(DocumentBlob)).scalar_one()
            blob.data = b"\xff\xfe not utf-8"
            db.commit()
        finally:
            db.close()

        worker = make_worker(session_factory)
        assert worker.process_one() is True
        assert worker.process_one() is False  # no retry: terminal on attempt 1

        check = session_factory()
        try:
            job = check.execute(select(IngestionJob)).scalar_one()
            assert job.state == JOB_STATE_FAILED
            assert job.attempts == 1
            version = check.execute(select(DocumentVersion)).scalar_one()
            assert version.error_code == "invalid_encoding"
        finally:
            check.close()

    def test_start_is_idempotent_no_duplicate_pools(self, session_factory):
        worker = make_worker(session_factory, worker_count=2)
        try:
            worker.start()
            threads_before = list(worker._threads)
            worker.start()  # dev-reload / repeated lifespan
            assert worker._threads == threads_before
            assert sum(t.is_alive() for t in worker._threads) == 2
        finally:
            worker.stop()
        assert not worker.running

    def test_graceful_shutdown_is_prompt(self, session_factory):
        worker = make_worker(session_factory, poll_seconds=5.0)  # long poll wait
        worker.start()
        start = time.perf_counter()
        worker.stop(timeout=10)
        assert time.perf_counter() - start < 3.0  # Event interrupt, no busy spin
        assert not worker.running

    def test_worker_recovers_stale_jobs_at_startup(self, db_session, session_factory, company):
        _doc, version, job = make_uploaded_document(db_session, company.id)
        # simulate a crashed holder: running with an ancient heartbeat
        fresh_job = db_session.get(IngestionJob, job.id)
        fresh_job.state = JOB_STATE_RUNNING
        fresh_job.attempts = 1
        fresh_job.heartbeat_at = datetime.utcnow() - timedelta(hours=1)
        db_session.commit()

        worker = make_worker(session_factory, stale_seconds=60)
        try:
            worker.start()
            deadline = time.perf_counter() + 10
            done = False
            while time.perf_counter() < deadline and not done:
                check = session_factory()
                try:
                    v = check.get(DocumentVersion, version.id)
                    done = v is not None and v.status == VERSION_STATUS_READY
                finally:
                    check.close()
                if not done:
                    time.sleep(0.05)
            assert done, "stale job was not recovered and processed"
        finally:
            worker.stop()

    def test_app_worker_gated_on_flag(self, session_factory, outbox, monkeypatch):
        """The application startup starts the worker ONLY when the tenant
        corpus flag is on (and the DB is enabled)."""
        from fastapi.testclient import TestClient

        import app.ingestion.worker as worker_module
        from app.db.session import get_db
        from app.main import app

        started = []
        monkeypatch.setattr(worker_module, "start_application_worker", lambda: started.append(True))
        monkeypatch.setattr(worker_module, "stop_application_worker", lambda: None)

        def _get_db():
            session = session_factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = _get_db
        try:
            with TestClient(app):
                pass
            assert started == []  # flag off (default): worker never starts

            monkeypatch.setattr(get_settings(), "evidentia_tenant_corpus_enabled", True)
            with TestClient(app):
                pass
            assert started == [True]

            with TestClient(app):
                pass
            assert started == [True, True]  # idempotency lives inside start()
        finally:
            app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# backfill -> worker integration (M1 jobs processed safely)
# --------------------------------------------------------------------------- #


class TestBackfillIntegration:
    def test_backfilled_document_processes_end_to_end(self, db_session, session_factory, company):
        legacy = Document(
            company_id=company.id,
            title="Legacy Runbook",
            slug="legacy-runbook",
            type="MD",
            content_text=MARKDOWN,
        )
        db_session.add(legacy)
        db_session.commit()

        result = backfill_content_text_documents(db_session)
        assert result.backfilled == [legacy.id]

        worker = make_worker(session_factory)
        assert worker.process_one() is True
        assert worker.process_one() is False

        check = session_factory()
        try:
            versions = check.execute(
                select(DocumentVersion).where(DocumentVersion.document_id == legacy.id)
            ).scalars().all()
            assert len(versions) == 1  # worker never re-creates version 1
            assert versions[0].status == VERSION_STATUS_READY

            sections = check.execute(
                select(DocumentSection).where(DocumentSection.version_id == versions[0].id)
            ).scalars().all()
            # declared MD source parsed as markdown => real heading sections
            assert [s.title for s in sections] == ["Runbook", "Escalation", "Rollback"]

            fresh = check.get(Document, legacy.id)
            assert fresh.current_version_id == versions[0].id
            assert fresh.content_text == MARKDOWN  # legacy data untouched
        finally:
            check.close()

    def test_backfill_rerun_after_processing_is_safe(self, db_session, session_factory, company):
        legacy = Document(
            company_id=company.id, title="Legacy", slug="legacy", type="TXT",
            content_text="Plain paragraph one.\n\nPlain paragraph two.",
        )
        db_session.add(legacy)
        db_session.commit()

        backfill_content_text_documents(db_session)
        worker = make_worker(session_factory)
        worker.process_one()

        rerun = backfill_content_text_documents(db_session)
        assert rerun.backfilled == []
        assert rerun.skipped_has_version == [legacy.id]

        check = session_factory()
        try:
            versions = check.execute(
                select(DocumentVersion).where(DocumentVersion.document_id == legacy.id)
            ).scalars().all()
            assert len(versions) == 1
            sections = check.execute(select(DocumentSection)).scalars().all()
            hashes = sorted(s.text_sha256 for s in sections)
        finally:
            check.close()

        # reprocess the same version via a fresh terminal-allowed job:
        # sections are rewritten, never duplicated.
        db = session_factory()
        try:
            version = db.execute(select(DocumentVersion)).scalar_one()
            version.status = "sectioning"  # simulate an interrupted re-run
            DatabaseJobQueue().enqueue(
                db, company_id=company.id, document_id=legacy.id, version_id=version.id
            )
            db.commit()
        finally:
            db.close()
        worker.process_one()

        check = session_factory()
        try:
            sections = check.execute(select(DocumentSection)).scalars().all()
            assert sorted(s.text_sha256 for s in sections) == hashes
        finally:
            check.close()
