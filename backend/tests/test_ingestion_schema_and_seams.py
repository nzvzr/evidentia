"""M1 — ingestion schema, Protocol seams, feature flag, backfill.

M1's promise is *foundation without behavior change*: additive tables and
columns, seams the later milestones implement against, a flag that defaults
off, and an idempotent backfill. The tests here pin four things:

1. the schema's integrity constraints actually hold (uniqueness, 1–1 blob);
2. the seams round-trip (BlobStore) and are idempotent (JobQueue enqueue),
   tenant-scoped where they read;
3. the public documents API response shape is byte-for-byte unchanged;
4. the backfill follows the crash-safe write order, is idempotent, and never
   marks anything `ready` (sectionization does not exist until M2).
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy.exc import IntegrityError

from app.agents.document_reader import document_reader
from app.agents.section_provider import DemoCorpusProvider
from app.core.config import Settings
from app.models.db_models import (
    JOB_STATE_QUEUED,
    JOB_STATE_SUCCEEDED,
    Company,
    Document,
    DocumentBlob,
    DocumentSection,
    DocumentVersion,
    IngestionJob,
)
from app.db.base import Base
from app.db.session import create_application_engine
from app.repositories.documents import delete_document
from app.services.blob_store import DatabaseBlobStore
from app.services.document_backfill import backfill_content_text_documents
from app.services.job_queue import DatabaseJobQueue

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker


# --------------------------------------------------------------------------- #
# Fixtures: a tenant with a plain content_text document (the pre-M1 shape)
# --------------------------------------------------------------------------- #


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


def make_document(db, company_id: str, title: str = "Runbook", content: str | None = "## Escalation\nPage the on-call.") -> Document:
    doc = Document(company_id=company_id, title=title, slug=title.lower(), content_text=content)
    db.add(doc)
    db.commit()
    return doc


def make_version(db, doc: Document, version_no: int = 1) -> DocumentVersion:
    version = DocumentVersion(document_id=doc.id, company_id=doc.company_id, version_no=version_no)
    db.add(version)
    db.commit()
    return version


# --------------------------------------------------------------------------- #
# Feature flag
# --------------------------------------------------------------------------- #


class TestFeatureFlag:
    def test_tenant_corpus_flag_defaults_off(self):
        # _env_file=None: the field default must be off regardless of any local .env.
        assert Settings(_env_file=None).evidentia_tenant_corpus_enabled is False


# --------------------------------------------------------------------------- #
# Schema integrity
# --------------------------------------------------------------------------- #


class TestSchemaConstraints:
    def test_version_no_unique_per_document(self, db_session, company):
        doc = make_document(db_session, company.id)
        make_version(db_session, doc, 1)
        with pytest.raises(IntegrityError):
            make_version(db_session, doc, 1)
        db_session.rollback()

    def test_anchor_unique_per_version(self, db_session, company):
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)
        for ordinal in (0, 1):
            db_session.add(
                DocumentSection(
                    company_id=company.id,
                    document_id=doc.id,
                    version_id=version.id,
                    anchor_id="k3f9x",  # same anchor twice in one version
                    citation_id=f"RUN-{ordinal}",
                    ordinal=ordinal,
                    title="Escalation",
                    text="Page the on-call.",
                )
            )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_ordinal_unique_per_version(self, db_session, company):
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)
        for anchor in ("a1", "a2"):
            db_session.add(
                DocumentSection(
                    company_id=company.id,
                    document_id=doc.id,
                    version_id=version.id,
                    anchor_id=anchor,
                    citation_id=f"RUN-{anchor}",
                    ordinal=0,  # duplicate ordinal
                    title="Escalation",
                    text="Page the on-call.",
                )
            )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_blob_is_one_to_one_with_version(self, db_session, company):
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)
        store = DatabaseBlobStore()
        store.put(db_session, company_id=company.id, version_id=version.id, data=b"one")
        db_session.commit()
        with pytest.raises(IntegrityError):
            store.put(db_session, company_id=company.id, version_id=version.id, data=b"two")
        db_session.rollback()

    def test_new_document_columns_default_inert(self, db_session, company):
        """A document created exactly the way the API creates one today must
        come out with inert ingestion state: no version, no prefix, status 'empty'."""
        doc = make_document(db_session, company.id)
        db_session.refresh(doc)
        assert doc.status == "empty"
        assert doc.source_type == "api"
        assert doc.current_version_id is None
        assert doc.citation_prefix is None
        assert doc.deleted_at is None

    def test_citation_prefix_unique_per_tenant(self, db_session, company):
        """citation_prefix is identity: two documents in one tenant can never
        share a citation family, and the DATABASE enforces it (M3 minting must
        not depend on a check-then-insert)."""
        first = make_document(db_session, company.id, title="First")
        first.citation_prefix = "RUN"
        db_session.commit()

        second = make_document(db_session, company.id, title="Second")
        second.citation_prefix = "RUN"
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_citation_prefix_may_repeat_across_tenants(self, db_session, company, other_company):
        ours = make_document(db_session, company.id, title="Ours")
        ours.citation_prefix = "RUN"
        theirs = make_document(db_session, other_company.id, title="Theirs")
        theirs.citation_prefix = "RUN"
        db_session.commit()
        assert ours.citation_prefix == theirs.citation_prefix == "RUN"

    def test_null_citation_prefixes_coexist(self, db_session, company):
        """NULL means 'not yet minted' (pre-M3), and every document starts
        there — NULLs must be distinct under the unique index."""
        a = make_document(db_session, company.id, title="A")
        b = make_document(db_session, company.id, title="B")
        db_session.commit()
        assert a.citation_prefix is None and b.citation_prefix is None


# --------------------------------------------------------------------------- #
# Application engine — SQLite foreign keys are actually ON
# --------------------------------------------------------------------------- #


class TestApplicationEngineForeignKeys:
    def test_document_delete_is_soft_and_preserves_source_history(self, tmp_path):
        """M4 deletion hides the document but retains immutable source rows."""
        eng = create_application_engine(f"sqlite:///{tmp_path / 'app.db'}")
        Base.metadata.create_all(bind=eng)
        factory = sessionmaker(bind=eng, autoflush=False, autocommit=False, future=True)
        db = factory()
        try:
            company = Company(name="Acme", slug="acme")
            db.add(company)
            db.commit()
            doc = make_document(db, company.id)
            version = make_version(db, doc)
            DatabaseBlobStore().put(db, company_id=company.id, version_id=version.id, data=b"bytes")
            DatabaseJobQueue().enqueue(
                db, company_id=company.id, document_id=doc.id, version_id=version.id
            )
            db.commit()

            assert delete_document(db, doc.id, company.id) is True
            db.commit()

            db.expire_all()
            assert db.get(Document, doc.id).deleted_at is not None
            assert len(db.execute(select(DocumentVersion)).scalars().all()) == 1
            assert len(db.execute(select(DocumentBlob)).scalars().all()) == 1
            assert len(db.execute(select(IngestionJob)).scalars().all()) == 1
        finally:
            db.close()
            eng.dispose()


# --------------------------------------------------------------------------- #
# Public API shape — byte-for-byte guard
# --------------------------------------------------------------------------- #


class TestDocumentsApiUnchanged:
    def test_serialization_gains_no_new_keys(self, alice):
        """M1 must not leak ingestion columns into the documents API: response
        shape changes are an M2 deliverable, and with the corpus flag off the
        behavior contract is 'byte-for-byte today'."""
        res = alice.post("/api/documents", json={"title": "Runbook", "contentText": "## A\nBody."})
        assert res.status_code == 201, res.text
        assert set(res.json().keys()) == {
            "id",
            "companyId",
            "title",
            "slug",
            "type",
            "category",
            "metadata",
            "createdAt",
        }


# --------------------------------------------------------------------------- #
# BlobStore seam
# --------------------------------------------------------------------------- #


class TestDatabaseBlobStore:
    def test_put_get_delete_roundtrip(self, db_session, company):
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)
        store = DatabaseBlobStore()

        blob = store.put(db_session, company_id=company.id, version_id=version.id, data=b"raw bytes")
        db_session.commit()
        assert blob.byte_size == 9
        assert blob.storage_key == f"db:{blob.id}"

        assert store.get(db_session, version_id=version.id, company_id=company.id) == b"raw bytes"
        assert store.delete(db_session, version_id=version.id, company_id=company.id) is True
        db_session.commit()
        assert store.get(db_session, version_id=version.id, company_id=company.id) is None
        assert store.delete(db_session, version_id=version.id, company_id=company.id) is False

    def test_reads_are_tenant_scoped(self, db_session, company, other_company):
        """Another tenant's blob is indistinguishable from a missing one — the
        same absence-shaped doctrine as every repository lookup."""
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)
        store = DatabaseBlobStore()
        store.put(db_session, company_id=company.id, version_id=version.id, data=b"secret")
        db_session.commit()

        assert store.get(db_session, version_id=version.id, company_id=other_company.id) is None
        assert store.delete(db_session, version_id=version.id, company_id=other_company.id) is False
        # And the rightful tenant's blob survived the foreign delete attempt.
        assert store.get(db_session, version_id=version.id, company_id=company.id) == b"secret"


# --------------------------------------------------------------------------- #
# JobQueue seam
# --------------------------------------------------------------------------- #


class TestDatabaseJobQueue:
    def test_enqueue_is_idempotent_per_live_version(self, db_session, company):
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)
        queue = DatabaseJobQueue()

        first = queue.enqueue(db_session, company_id=company.id, document_id=doc.id, version_id=version.id)
        second = queue.enqueue(db_session, company_id=company.id, document_id=doc.id, version_id=version.id)
        db_session.commit()
        assert first.id == second.id
        assert first.state == JOB_STATE_QUEUED
        assert first.attempts == 0

    def test_terminal_job_allows_reenqueue(self, db_session, company):
        """Re-ingestion (e.g. after a parser upgrade) needs a fresh job once the
        old one is terminal; only *live* jobs deduplicate."""
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)
        queue = DatabaseJobQueue()

        first = queue.enqueue(db_session, company_id=company.id, document_id=doc.id, version_id=version.id)
        first.state = JOB_STATE_SUCCEEDED
        db_session.commit()

        second = queue.enqueue(db_session, company_id=company.id, document_id=doc.id, version_id=version.id)
        db_session.commit()
        assert second.id != first.id
        assert second.state == JOB_STATE_QUEUED

    def test_database_rejects_two_live_jobs_per_version(self, db_session, company):
        """The partial unique index is the authority behind enqueue's
        idempotency: even code that bypasses the queue cannot create two
        queued/running jobs for one version."""
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)
        for _ in range(2):
            db_session.add(
                IngestionJob(
                    company_id=company.id,
                    document_id=doc.id,
                    version_id=version.id,
                    state=JOB_STATE_QUEUED,
                )
            )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_terminal_jobs_fall_outside_the_live_index(self, db_session, company):
        """Succeeded/failed history rows accumulate freely; only live states
        are constrained."""
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)
        db_session.add(
            IngestionJob(
                company_id=company.id, document_id=doc.id, version_id=version.id, state=JOB_STATE_SUCCEEDED
            )
        )
        db_session.add(
            IngestionJob(
                company_id=company.id, document_id=doc.id, version_id=version.id, state="failed"
            )
        )
        db_session.add(
            IngestionJob(
                company_id=company.id, document_id=doc.id, version_id=version.id, state=JOB_STATE_QUEUED
            )
        )
        db_session.commit()
        rows = db_session.execute(
            select(IngestionJob).where(IngestionJob.version_id == version.id)
        ).scalars().all()
        assert len(rows) == 3

    def test_lost_enqueue_race_adopts_survivor_and_preserves_outer_work(
        self, db_session, session_factory, company, monkeypatch
    ):
        """The losing side of the enqueue race must (a) not surface
        IntegrityError, (b) return the surviving live job, and (c) not roll
        back unrelated work already pending in the caller's transaction.

        The race window (both sessions observing 'no live job') is simulated
        deterministically by making the loser's pre-select miss once; the
        winner's job is already committed, so the loser's insert hits the
        partial unique index exactly as it would mid-race.
        """
        doc = make_document(db_session, company.id)
        version = make_version(db_session, doc)

        winner_session = session_factory()
        try:
            winner = DatabaseJobQueue().enqueue(
                winner_session, company_id=company.id, document_id=doc.id, version_id=version.id
            )
            winner_session.commit()
            winner_id = winner.id
        finally:
            winner_session.close()

        real_live_job = DatabaseJobQueue._live_job
        calls = {"n": 0}

        def miss_first(self, db, company_id, version_id):
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # the loser's stale 'no live job' observation
            return real_live_job(self, db, company_id, version_id)

        monkeypatch.setattr(DatabaseJobQueue, "_live_job", miss_first)

        # Unrelated pending work in the same outer transaction.
        doc.title = "Renamed while enqueueing"

        resolved = DatabaseJobQueue().enqueue(
            db_session, company_id=company.id, document_id=doc.id, version_id=version.id
        )
        assert resolved.id == winner_id
        db_session.commit()

        check = session_factory()
        try:
            live = check.execute(
                select(IngestionJob).where(
                    IngestionJob.version_id == version.id,
                    IngestionJob.state.in_((JOB_STATE_QUEUED, "running")),
                )
            ).scalars().all()
            assert [job.id for job in live] == [winner_id]
            surviving_doc = check.get(Document, doc.id)
            assert surviving_doc.title == "Renamed while enqueueing"
        finally:
            check.close()


# --------------------------------------------------------------------------- #
# SectionProvider seam
# --------------------------------------------------------------------------- #


class TestDemoCorpusProvider:
    def test_output_is_identical_to_document_reader(self):
        provider = DemoCorpusProvider()
        for selection in ([], ["security-compliance-whitepaper"], ["unknown-id"]):
            assert provider.load(selection) == document_reader(selection)


# --------------------------------------------------------------------------- #
# Backfill
# --------------------------------------------------------------------------- #


class TestBackfill:
    def test_backfills_version_blob_and_job(self, db_session, company):
        text = "## Escalation\nPage the on-call within 5 minutes."
        doc = make_document(db_session, company.id, content=text)

        result = backfill_content_text_documents(db_session)
        assert result.backfilled == [doc.id]

        version = db_session.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
        ).scalar_one()
        assert version.version_no == 1
        assert version.status == "pending"  # never ready before sectionization (M2)
        assert version.content_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert version.char_count == len(text)

        blob = db_session.execute(
            select(DocumentBlob).where(DocumentBlob.version_id == version.id)
        ).scalar_one()
        assert blob.data == text.encode("utf-8")
        assert blob.byte_size == len(text.encode("utf-8"))
        assert blob.company_id == company.id

        job = db_session.execute(
            select(IngestionJob).where(IngestionJob.version_id == version.id)
        ).scalar_one()
        assert job.state == JOB_STATE_QUEUED

        db_session.refresh(doc)
        assert doc.status == "processing"
        assert doc.current_version_id is None  # only ever flips to a ready version
        assert doc.content_sha256 == version.content_sha256
        assert doc.size_bytes == len(text.encode("utf-8"))
        assert doc.mime_type == "text/plain"
        assert doc.content_text == text  # deprecated but untouched (no data loss)

    def test_rerun_is_idempotent(self, db_session, company):
        doc = make_document(db_session, company.id)
        first = backfill_content_text_documents(db_session)
        assert first.backfilled == [doc.id]

        second = backfill_content_text_documents(db_session)
        assert second.backfilled == []
        assert second.skipped_has_version == [doc.id]
        versions = db_session.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
        ).scalars().all()
        assert len(versions) == 1

    def test_skips_documents_without_content(self, db_session, company):
        empty = make_document(db_session, company.id, title="Empty", content=None)
        blank = make_document(db_session, company.id, title="Blank", content="   \n")
        result = backfill_content_text_documents(db_session)
        assert set(result.skipped_no_content) == {empty.id, blank.id}
        assert result.backfilled == []
        count = db_session.execute(select(DocumentVersion)).scalars().all()
        assert count == []

    def test_company_filter_restricts_the_run(self, db_session, company, other_company):
        ours = make_document(db_session, company.id, title="Ours")
        theirs = make_document(db_session, other_company.id, title="Theirs")

        result = backfill_content_text_documents(db_session, company_id=company.id)
        assert result.backfilled == [ours.id]
        remaining = db_session.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == theirs.id)
        ).scalars().all()
        assert remaining == []

    def test_dry_run_writes_nothing(self, db_session, company):
        doc = make_document(db_session, company.id)
        result = backfill_content_text_documents(db_session, dry_run=True)
        assert result.backfilled == [doc.id]
        assert db_session.execute(select(DocumentVersion)).scalars().all() == []
        assert db_session.execute(select(IngestionJob)).scalars().all() == []
        db_session.refresh(doc)
        assert doc.status == "empty"
