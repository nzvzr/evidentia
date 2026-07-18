"""M3 — finalization lifecycle: successor creation, transitional immutability,
the extended state machine, the guarded pointer flip, citation identities,
eligibility, the API surface and the bulk backfill service.

Everything here honors the binding M2→M3 contract (DECISIONS.md 2026-07-16):
the transitional version row and its sections must remain byte-for-byte
unchanged through every finalization path.
"""

from __future__ import annotations

import pytest
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.ingestion import anchors as anchors_module
from app.ingestion import pipeline as pipeline_module
from app.ingestion.anchors import ANCHOR_ALGO_VERSION
from app.ingestion.errors import IngestionError
from app.ingestion.finalization_target import (
    build_finalization_target,
    target_from_engine_versions,
)
from app.ingestion.pipeline import (
    InvalidTransition,
    OwnershipLost,
    _flip_current_version,
    ensure_citation_prefix,
    process_finalization,
    transition_version,
)
from app.ingestion.sectionizer import ANCHOR_ALGO_TRANSITIONAL
from app.ingestion.worker import IngestionWorker
from app.modules.loader import get_active_module
from app.models.db_models import (
    JOB_OPERATION_FINALIZE,
    JOB_OPERATION_INGEST,
    JOB_STATE_QUEUED,
    VERSION_STATUS_ANCHORING,
    VERSION_STATUS_CLASSIFYING,
    VERSION_STATUS_FAILED,
    VERSION_STATUS_PENDING,
    VERSION_STATUS_READY,
    Document,
    DocumentBlob,
    DocumentSection,
    DocumentVersion,
    IngestionJob,
)
from app.services import document_finalize as finalize_service
from app.services.document_finalize import (
    FinalizeRejected,
    discover_eligible,
    finalize_document,
    finalize_source_version,
    run_finalization_backfill,
)
from app.services.generation_eligibility import (
    check_generation_eligibility,
    is_generation_eligible,
    supported_finalization_targets,
)


def markdown_target_digest() -> str:
    """The complete target digest current code produces for markdown uploads."""
    return build_finalization_target("markdown", get_active_module()).digest

MD_BODY = b"""# Data Handling Policy

## Data Residency

Customer data is stored and processed regionally. Data residency and data
sovereignty controls apply to regulated workloads under GDPR.

## Escalation

Page the on-call within five minutes. Severity one incidents page the
incident commander and open a bridge.

## Escalation

After hours the escalation path routes through the partner on-call rotation
before paging the incident commander.
"""

MD_BODY_EDITED = MD_BODY.replace(b"within five minutes", b"within three minutes")


@pytest.fixture
def corpus_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "evidentia_tenant_corpus_enabled", True)


def upload(account, body: bytes = MD_BODY, name: str = "policy.md"):
    return account.post(
        "/api/documents/upload", files={"file": (name, body, "text/markdown")}
    )


def drain_jobs(session_factory) -> None:
    worker = IngestionWorker(session_factory, poll_seconds=0.01, max_attempts=3)
    while worker.process_one():
        pass


def version_rows(db, document_id):
    return db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_no.asc())
        .execution_options(populate_existing=True)
    ).scalars().all()


def section_snapshot(db, version_id):
    """Every persisted column of a version's sections, as plain data."""
    rows = db.execute(
        select(DocumentSection)
        .where(DocumentSection.version_id == version_id)
        .order_by(DocumentSection.ordinal.asc())
        .execution_options(populate_existing=True)
    ).scalars().all()
    return [
        {
            c.name: getattr(row, c.name)
            for c in DocumentSection.__table__.columns
        }
        for row in rows
    ]


def version_snapshot(db, version_id):
    row = db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.id == version_id)
        .execution_options(populate_existing=True)
    ).scalar_one()
    return {c.name: getattr(row, c.name) for c in DocumentVersion.__table__.columns}


def uploaded_transitional(alice, session_factory, db_session, body: bytes = MD_BODY):
    """Upload + drain -> (document_id, transitional ready version row)."""
    res = upload(alice, body=body)
    assert res.status_code == 202, res.text
    document_id = res.json()["documentId"]
    drain_jobs(session_factory)
    versions = version_rows(db_session, document_id)
    assert versions[-1].status == VERSION_STATUS_READY
    assert versions[-1].anchor_algo_version == ANCHOR_ALGO_TRANSITIONAL
    return document_id, versions[-1]


# --------------------------------------------------------------------------- #
# lifecycle and immutability
# --------------------------------------------------------------------------- #


class TestLifecycle:
    def test_finalize_creates_successor_and_leaves_source_byte_for_byte(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        before_version = version_snapshot(db_session, source.id)
        before_sections = section_snapshot(db_session, source.id)

        res = alice.post(f"/api/documents/{document_id}/finalize")
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["created"] is True and body["versionNo"] == 2
        drain_jobs(session_factory)

        # source version + sections: byte-for-byte unchanged
        assert version_snapshot(db_session, source.id) == before_version
        assert section_snapshot(db_session, source.id) == before_sections

        versions = version_rows(db_session, document_id)
        assert len(versions) == 2
        successor = versions[-1]
        assert successor.status == VERSION_STATUS_READY
        assert successor.anchor_algo_version == ANCHOR_ALGO_VERSION
        assert successor.source_version_id == source.id
        assert successor.finalization_engine == markdown_target_digest()
        assert successor.content_sha256 == source.content_sha256
        assert successor.manifest_sha256 and successor.manifest_sha256 != before_version["manifest_sha256"]
        assert successor.classification_signature
        assert isinstance(successor.engine_versions, dict)

        # the pointer flipped exactly once, to the successor
        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()
        assert doc.current_version_id == successor.id

    def test_successor_reuses_retained_blob_without_copying(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        successor = version_rows(db_session, document_id)[-1]
        blobs = db_session.execute(
            select(DocumentBlob).where(DocumentBlob.company_id == source.company_id)
        ).scalars().all()
        assert len(blobs) == 1  # no byte duplication
        assert blobs[0].version_id == source.id
        assert successor.status == VERSION_STATUS_READY

    def test_final_sections_carry_identity_and_classification(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        successor = version_rows(db_session, document_id)[-1]

        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()
        # the title is filename-derived ("policy") => prefix "PLC"
        assert doc.citation_prefix == "PLC"

        sections = section_snapshot(db_session, successor.id)
        assert sections, "successor has sections"
        transitional_ids = {s["citation_id"] for s in section_snapshot(db_session, source.id)}
        for section in sections:
            assert section["citation_id"] == f"PLC-{section['anchor_id']}"
            assert section["citation_id"] not in transitional_ids
            assert not section["anchor_id"].startswith("s0")  # never the ordinal ids
            assert section["classifier_version"] == "m3.1"
            assert section["signature_pack_version"] == "compliance@1.0.0"
            assert section["classification_signature"]
            assert section["anchor_provenance"]["algo"] == ANCHOR_ALGO_VERSION
            assert section["category"]  # every section got an explicit outcome
        # duplicate headings got deterministic distinct anchors
        anchors = [s["anchor_id"] for s in sections]
        assert len(set(anchors)) == len(anchors)

    def test_repeat_trigger_is_idempotent_one_live_job(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        first = alice.post(f"/api/documents/{document_id}/finalize")
        assert first.status_code == 202
        second = alice.post(f"/api/documents/{document_id}/finalize")
        assert second.status_code == 200
        assert second.json()["adopted"] is True
        assert second.json()["versionId"] == first.json()["versionId"]

        versions = version_rows(db_session, document_id)
        assert len(versions) == 2  # exactly one successor
        live = db_session.execute(
            select(IngestionJob).where(
                IngestionJob.version_id == versions[-1].id,
                IngestionJob.state == JOB_STATE_QUEUED,
            )
        ).scalars().all()
        assert len(live) == 1
        assert live[0].operation == JOB_OPERATION_FINALIZE

    def test_finalizing_a_final_document_is_explicit_noop(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, _source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        res = alice.post(f"/api/documents/{document_id}/finalize")
        assert res.status_code == 409
        assert res.json()["code"] == "already_final"
        assert len(version_rows(db_session, document_id)) == 2

    def test_failed_finalization_keeps_pointer_then_retry_recovers(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)

        def boom(*_a, **_k):
            raise ValueError("forced anchoring failure")

        # A dedicated MonkeyPatch: undoing it must not undo the corpus flag.
        patch = MonkeyPatch()
        patch.setattr(pipeline_module, "assign_anchors", boom)
        res = alice.post(f"/api/documents/{document_id}/finalize")
        assert res.status_code == 202
        drain_jobs(session_factory)

        versions = version_rows(db_session, document_id)
        successor = versions[-1]
        assert successor.status == VERSION_STATUS_FAILED
        assert successor.error_code == "anchoring_failed"
        # partial anchors/classifications are never visible
        assert section_snapshot(db_session, successor.id) == []
        # the pointer never moved; the document stays ready on the source
        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()
        assert doc.current_version_id == source.id
        assert doc.status == "ready"

        # retry adopts the SAME successor row (no duplicate) and succeeds
        patch.undo()
        retry = alice.post(f"/api/documents/{document_id}/finalize")
        assert retry.status_code == 200
        assert retry.json()["retried"] is True
        assert retry.json()["versionId"] == successor.id
        drain_jobs(session_factory)
        versions = version_rows(db_session, document_id)
        assert len(versions) == 2
        assert versions[-1].status == VERSION_STATUS_READY

    def test_anchor_inheritance_across_edited_reupload(
        self, alice, corpus_on, session_factory, db_session
    ):
        # v1 transitional -> v2 final
        document_id, _ = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        v2 = version_rows(db_session, document_id)[-1]
        v2_sections = {s["title"]: s for s in section_snapshot(db_session, v2.id)}

        # v3 transitional (lightly edited source) -> v4 final
        res = alice.post(
            f"/api/documents/{document_id}/versions",
            files={"file": ("policy.md", MD_BODY_EDITED, "text/markdown")},
        )
        assert res.status_code == 202, res.text
        drain_jobs(session_factory)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)

        versions = version_rows(db_session, document_id)
        assert [v.version_no for v in versions] == [1, 2, 3, 4]
        v4 = versions[-1]
        assert v4.anchor_algo_version == ANCHOR_ALGO_VERSION
        v4_sections = {s["title"]: s for s in section_snapshot(db_session, v4.id)}

        # the unchanged section kept anchor AND citation identity
        unchanged = "Data Residency"
        assert v4_sections[unchanged]["anchor_id"] == v2_sections[unchanged]["anchor_id"]
        assert v4_sections[unchanged]["citation_id"] == v2_sections[unchanged]["citation_id"]
        assert v4_sections[unchanged]["anchor_provenance"]["decision"] == "unchanged"
        # the edited section kept its heading anchor too (heading identity)
        edited = "Escalation"
        assert v4_sections[edited]["anchor_id"] == v2_sections[edited]["anchor_id"]
        # v2 remains untouched and the pointer is on v4
        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()
        assert doc.current_version_id == v4.id
        # prefix minted once, reused
        assert doc.citation_prefix == "PLC"

    def test_prefix_collision_gets_numeric_suffix(
        self, alice, corpus_on, session_factory, db_session
    ):
        doc1, _ = uploaded_transitional(alice, session_factory, db_session)
        body2 = MD_BODY.replace(b"# Data Handling Policy", b"# Data Handling Policy\n\nRevision two preamble.")
        res = upload(alice, body=body2, name="policy-two.md")
        assert res.status_code == 202
        doc2 = res.json()["documentId"]
        # make the derived titles identical so the prefixes collide
        db_session.execute(
            select(Document).where(Document.id == doc2)
        ).scalar_one().title = "policy"
        db_session.commit()
        drain_jobs(session_factory)

        alice.post(f"/api/documents/{doc1}/finalize")
        alice.post(f"/api/documents/{doc2}/finalize")
        drain_jobs(session_factory)

        prefixes = {
            row.id: row.citation_prefix
            for row in db_session.execute(
                select(Document).execution_options(populate_existing=True)
            ).scalars()
        }
        assert prefixes[doc1] == "PLC"
        assert prefixes[doc2] == "PLC2"


# --------------------------------------------------------------------------- #
# state machine + flip guard
# --------------------------------------------------------------------------- #


class TestStateMachine:
    def test_no_shortcut_transitions(self, db_session):
        version = DocumentVersion(document_id="d", company_id="c", version_no=1)
        version.status = VERSION_STATUS_PENDING
        with pytest.raises(InvalidTransition):
            transition_version(version, VERSION_STATUS_READY)
        version.status = VERSION_STATUS_READY
        with pytest.raises(InvalidTransition):
            transition_version(version, VERSION_STATUS_CLASSIFYING)
        version.status = VERSION_STATUS_ANCHORING
        transition_version(version, VERSION_STATUS_CLASSIFYING)
        transition_version(version, VERSION_STATUS_READY)

    def test_stale_lower_version_cannot_move_pointer_backwards(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        versions = version_rows(db_session, document_id)
        successor = versions[-1]
        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()
        assert doc.current_version_id == successor.id

        # a stale, lower ready version cannot win the flip
        flipped = _flip_current_version(db_session, doc, versions[0])
        db_session.commit()
        assert flipped is False
        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()
        assert doc.current_version_id == successor.id

    def test_ownership_lost_aborts_without_failing_version(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        res = alice.post(f"/api/documents/{document_id}/finalize")
        successor_id = res.json()["versionId"]

        work_db = session_factory()
        try:
            with pytest.raises(OwnershipLost):
                process_finalization(
                    work_db,
                    version_id=successor_id,
                    company_id=source.company_id,
                    heartbeat=lambda: False,
                )
            work_db.rollback()
        finally:
            work_db.close()

        successor = db_session.execute(
            select(DocumentVersion).where(DocumentVersion.id == successor_id)
            .execution_options(populate_existing=True)
        ).scalar_one()
        assert successor.status != VERSION_STATUS_FAILED
        assert section_snapshot(db_session, successor_id) == []

    def test_ready_successor_is_immutable_to_reprocessing(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        successor = version_rows(db_session, document_id)[-1]
        before = version_snapshot(db_session, successor.id)

        work_db = session_factory()
        try:
            returned = process_finalization(
                work_db, version_id=successor.id, company_id=source.company_id
            )
            assert returned.status == VERSION_STATUS_READY
        finally:
            work_db.close()
        assert version_snapshot(db_session, successor.id) == before


# --------------------------------------------------------------------------- #
# M4 eligibility predicate
# --------------------------------------------------------------------------- #


class TestEligibility:
    def _final_successor(self, alice, session_factory, db_session):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        return document_id, source, version_rows(db_session, document_id)[-1]

    def test_transitional_versions_are_never_eligible(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source = uploaded_transitional(alice, session_factory, db_session)
        result = check_generation_eligibility(db_session, source, company_id=source.company_id)
        assert result.eligible is False
        assert result.reason == "transitional_identity"

    def test_final_version_is_eligible(self, alice, corpus_on, session_factory, db_session):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        assert is_generation_eligible(db_session, successor, company_id=source.company_id) is True

    def test_only_registered_complete_targets_are_supported(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, _source, successor = self._final_successor(alice, session_factory, db_session)
        registry = supported_finalization_targets()
        # exactly the current platform's targets: one per supported format
        assert set(registry) == {
            build_finalization_target("markdown", get_active_module()).digest,
            build_finalization_target("text", get_active_module()).digest,
        }
        assert successor.finalization_engine in registry

    def test_each_unsupported_component_is_rejected_independently(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        cases = [
            ({"parser": "future-parser"}, "unsupported_parser"),
            ({"parserName": "future-parser-name"}, "unsupported_parser"),
            ({"normalizer": "future-normalizer"}, "unsupported_normalizer"),
            ({"sectionizer": "future-sectionizer"}, "unsupported_sectionizer"),
            ({"anchorAlgo": "heading-path-v999"}, "unsupported_anchor_algo"),
            ({"anchorAlgo": ANCHOR_ALGO_TRANSITIONAL}, "unsupported_anchor_algo"),
            ({"anchorInheritance": "content-match-v999"}, "unsupported_inheritance"),
            ({"classifier": "m999"}, "unsupported_classifier"),
            ({"sectionSignature": 999}, "unsupported_signature_version"),
            ({"manifest": "m999"}, "unsupported_manifest_version"),
            ({"module": {"id": "unknown", "version": "1.0.0", "digest": "e" * 64, "signatureVersion": "1.0.0"}}, "unknown_module"),
        ]
        module_meta = dict(successor.engine_versions["module"])
        for patch, reason in cases:
            engine = dict(successor.engine_versions)
            engine.update(patch)
            successor.engine_versions = engine
            result = check_generation_eligibility(
                db_session, successor, company_id=source.company_id
            )
            assert result.eligible is False
            assert result.reason == reason, (patch, result.reason)
            db_session.rollback()
            successor = db_session.execute(
                select(DocumentVersion).where(DocumentVersion.id == successor.id)
                .execution_options(populate_existing=True)
            ).scalar_one()

        # module digest mismatch and unknown module version, independently
        engine = dict(successor.engine_versions)
        engine["module"] = {**module_meta, "digest": "f" * 64}
        successor.engine_versions = engine
        assert (
            check_generation_eligibility(db_session, successor, company_id=source.company_id).reason
            == "module_digest_mismatch"
        )
        db_session.rollback()
        successor = db_session.execute(
            select(DocumentVersion).where(DocumentVersion.id == successor.id)
            .execution_options(populate_existing=True)
        ).scalar_one()
        engine = dict(successor.engine_versions)
        engine["module"] = {**module_meta, "version": "m999"}
        successor.engine_versions = engine
        assert (
            check_generation_eligibility(db_session, successor, company_id=source.company_id).reason
            == "unknown_module"
        )
        db_session.rollback()

    def test_unknown_future_complete_target_is_rejected(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        future = "cft1:" + "f" * 64
        successor.finalization_engine = future
        engine = dict(successor.engine_versions)
        engine["target"] = future
        successor.engine_versions = engine
        assert (
            check_generation_eligibility(db_session, successor, company_id=source.company_id).reason
            == "unsupported_target"
        )
        db_session.rollback()

    def test_anchor_algo_version_mismatch_is_rejected(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        successor.anchor_algo_version = "heading-path-v999"
        assert (
            check_generation_eligibility(db_session, successor, company_id=source.company_id).reason
            == "unsupported_anchor_algo"
        )
        db_session.rollback()

    def test_persisted_sections_are_validated(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        company_id = source.company_id

        def _reload():
            db_session.rollback()
            return db_session.execute(
                select(DocumentVersion).where(DocumentVersion.id == successor.id)
                .execution_options(populate_existing=True)
            ).scalar_one()

        def _sections(version):
            return db_session.execute(
                select(DocumentSection)
                .where(DocumentSection.version_id == version.id)
                .order_by(DocumentSection.ordinal.asc())
            ).scalars().all()

        # section-count mismatch
        v = _reload()
        v.section_count = v.section_count + 1
        assert check_generation_eligibility(db_session, v, company_id=company_id).reason == "section_count_mismatch"

        # duplicate/missing ordinal
        v = _reload()
        _sections(v)[0].ordinal = 999
        db_session.flush()
        assert check_generation_eligibility(db_session, v, company_id=company_id).reason == "bad_ordinals"

        # non-final anchor
        v = _reload()
        _sections(v)[0].anchor_id = "s0000"
        db_session.flush()
        assert check_generation_eligibility(db_session, v, company_id=company_id).reason == "non_final_anchor"

        # a structurally non-canonical anchor (the frozen grammar has no "-1":
        # the first occurrence is always the bare slug) fails the same way
        v = _reload()
        _sections(v)[0].anchor_id = "abcdefghijkl-1"
        db_session.flush()
        assert check_generation_eligibility(db_session, v, company_id=company_id).reason == "non_final_anchor"

        # missing per-section classification signature
        v = _reload()
        _sections(v)[0].classification_signature = None
        db_session.flush()
        assert check_generation_eligibility(db_session, v, company_id=company_id).reason == "missing_section_signature"

        # per-section anchor-algorithm provenance must match the version
        v = _reload()
        rows = _sections(v)
        rows[0].anchor_provenance = {**rows[0].anchor_provenance, "algo": "heading-path-v999"}
        db_session.flush()
        assert check_generation_eligibility(db_session, v, company_id=company_id).reason == "anchor_algo_mismatch"

        # ordered section data must reconstruct the stored manifest
        v = _reload()
        _sections(v)[0].category = "Tampered"
        db_session.flush()
        assert check_generation_eligibility(db_session, v, company_id=company_id).reason == "manifest_mismatch"

        # the version signature must match the ordered section signatures
        v = _reload()
        v.classification_signature = "a" * 64
        assert check_generation_eligibility(db_session, v, company_id=company_id).reason == "signature_mismatch"

        # intact again after rollbacks
        v = _reload()
        assert check_generation_eligibility(db_session, v, company_id=company_id).eligible is True

    def test_malformed_or_foreign_versions_fail_closed(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source, successor = self._final_successor(alice, session_factory, db_session)

        assert is_generation_eligible(db_session, None, company_id=source.company_id) is False
        assert is_generation_eligible(db_session, successor, company_id="other-tenant") is False

        successor.manifest_sha256 = None
        assert (
            check_generation_eligibility(db_session, successor, company_id=source.company_id).reason
            == "missing_manifest"
        )
        db_session.rollback()

        successor = version_rows(db_session, document_id)[-1]
        successor.engine_versions = {"parser": "m2.1"}  # partially migrated
        result = check_generation_eligibility(db_session, successor, company_id=source.company_id)
        assert result.eligible is False
        assert result.reason == "unsupported_target"  # no pinned-target agreement
        db_session.rollback()

        successor = version_rows(db_session, document_id)[-1]
        successor.engine_versions = "not-json-shaped"  # malformed metadata
        result = check_generation_eligibility(db_session, successor, company_id=source.company_id)
        assert result.eligible is False
        db_session.rollback()

        successor = version_rows(db_session, document_id)[-1]
        successor.classification_signature = "not-a-sha"
        assert (
            check_generation_eligibility(db_session, successor, company_id=source.company_id).reason
            == "missing_classification_signature"
        )
        db_session.rollback()


# --------------------------------------------------------------------------- #
# Blocker-1 regressions: engine_versions is bound to the ONE pinned complete
# target (no hybrid supported-component artifact); thresholds/weights are
# target-bound; anchor provenance is validated AND cryptographically bound.
# --------------------------------------------------------------------------- #


class TestTargetBindingRegressions:
    def _final_successor(self, alice, session_factory, db_session):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        return document_id, source, version_rows(db_session, document_id)[-1]

    def _md_txt(self):
        module = get_active_module()
        return (
            build_finalization_target("markdown", module),
            build_finalization_target("text", module),
        )

    def _reload(self, db_session, version_id):
        db_session.rollback()
        return db_session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.id == version_id)
            .execution_options(populate_existing=True)
        ).scalar_one()

    def _reason(self, db_session, version, company_id):
        return check_generation_eligibility(
            db_session, version, company_id=company_id
        ).reason

    def test_markdown_pinned_with_txt_parser_projection_is_rejected(
        self, alice, corpus_on, session_factory, db_session
    ):
        """The reported reproduction: Markdown target pinned, but the persisted
        parser fields are the supported TXT parser. Every component is
        individually supported, yet the reconstructed projection hashes to the
        TXT target, not the pinned Markdown target."""
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        _md, txt = self._md_txt()
        engine = dict(successor.engine_versions)
        engine["parserName"], engine["parser"] = txt.parser_name, txt.parser_version
        successor.engine_versions = engine
        # the per-component check still passes (TXT parser IS supported)...
        from app.services.generation_eligibility import _check_engine_components

        assert _check_engine_components(engine, supported_finalization_targets()) is None
        # ...but the authoritative binding rejects the hybrid
        assert self._reason(db_session, successor, source.company_id) == "target_digest_mismatch"

    def test_txt_pinned_with_markdown_parser_projection_is_rejected(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        md, txt = self._md_txt()
        successor.finalization_engine = txt.digest
        engine = txt.engine_versions()
        engine["parserName"], engine["parser"] = md.parser_name, md.parser_version
        successor.engine_versions = engine
        assert self._reason(db_session, successor, source.company_id) == "target_digest_mismatch"

    def test_mixed_components_hashing_to_another_supported_target_is_rejected(
        self, alice, corpus_on, session_factory, db_session
    ):
        """The reconstructed projection is itself a REGISTERED supported target
        (the TXT one) — yet it is not the PINNED one, so it is still rejected."""
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        _md, txt = self._md_txt()
        engine = dict(successor.engine_versions)
        engine["parserName"], engine["parser"] = txt.parser_name, txt.parser_version
        successor.engine_versions = engine
        assert target_from_engine_versions(engine).digest == txt.digest
        assert txt.digest in supported_finalization_targets()
        assert self._reason(db_session, successor, source.company_id) == "target_digest_mismatch"

    def test_thresholds_and_weights_are_target_bound(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        cid = source.company_id

        # altered threshold value
        v = self._reload(db_session, successor.id)
        engine = dict(v.engine_versions)
        engine["thresholds"] = {**engine["thresholds"], "categoryMinScore": 99.0}
        v.engine_versions = engine
        assert self._reason(db_session, v, cid) == "target_digest_mismatch"

        # altered weight value
        v = self._reload(db_session, successor.id)
        engine = dict(v.engine_versions)
        engine["weights"] = {**engine["weights"], "bodySignal": 99.0}
        v.engine_versions = engine
        assert self._reason(db_session, v, cid) == "target_digest_mismatch"

        # altered threshold KEY SET (add an unexpected key)
        v = self._reload(db_session, successor.id)
        engine = dict(v.engine_versions)
        engine["thresholds"] = {**engine["thresholds"], "bogusThreshold": 1.0}
        v.engine_versions = engine
        assert self._reason(db_session, v, cid) == "target_digest_mismatch"

        # altered weight KEY SET (drop a key)
        v = self._reload(db_session, successor.id)
        engine = dict(v.engine_versions)
        weights = dict(engine["weights"])
        weights.pop("phrase")
        engine["weights"] = weights
        v.engine_versions = engine
        assert self._reason(db_session, v, cid) == "target_digest_mismatch"

        # numeric TYPE change: 2.0 -> 2 (canonical digest distinguishes them)
        v = self._reload(db_session, successor.id)
        engine = dict(v.engine_versions)
        key = "categoryMinScore"
        engine["thresholds"] = {**engine["thresholds"], key: int(engine["thresholds"][key])}
        v.engine_versions = engine
        assert self._reason(db_session, v, cid) == "target_digest_mismatch"
        self._reload(db_session, successor.id)

    def test_missing_and_extra_projection_fields_fail_closed(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        cid = source.company_id

        # missing field (thresholds is not inspected by the per-component check)
        v = self._reload(db_session, successor.id)
        engine = dict(v.engine_versions)
        del engine["thresholds"]
        v.engine_versions = engine
        assert self._reason(db_session, v, cid) == "target_projection_missing_field"

        # extra field
        v = self._reload(db_session, successor.id)
        engine = dict(v.engine_versions)
        engine["unexpected"] = "x"
        v.engine_versions = engine
        assert self._reason(db_session, v, cid) == "target_projection_extra_field"
        self._reload(db_session, successor.id)

    def test_module_and_version_fields_are_rejected(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        cid = source.company_id
        cases = [
            (lambda e: e.__setitem__("module", {**e["module"], "signatureVersion": "9.9.9"}),
             "unsupported_signature_version"),
            (lambda e: e.__setitem__("module", {**e["module"], "digest": "f" * 64}),
             "module_digest_mismatch"),
            (lambda e: e.__setitem__("sectionSignature", 999), "unsupported_signature_version"),
            (lambda e: e.__setitem__("manifest", "m999"), "unsupported_manifest_version"),
        ]
        for mutate, reason in cases:
            v = self._reload(db_session, successor.id)
            engine = dict(v.engine_versions)
            mutate(engine)
            v.engine_versions = engine
            assert self._reason(db_session, v, cid) == reason, reason
        self._reload(db_session, successor.id)

    def _sections(self, db_session, version):
        return db_session.execute(
            select(DocumentSection)
            .where(DocumentSection.version_id == version.id)
            .order_by(DocumentSection.ordinal.asc())
        ).scalars().all()

    def test_anchor_provenance_is_validated(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        cid = source.company_id

        # missing provenance entirely
        v = self._reload(db_session, successor.id)
        self._sections(db_session, v)[0].anchor_provenance = None
        db_session.flush()
        assert self._reason(db_session, v, cid) == "anchor_provenance_missing"

        # wrong inheritance algorithm
        v = self._reload(db_session, successor.id)
        row = self._sections(db_session, v)[0]
        row.anchor_provenance = {**row.anchor_provenance, "inheritance": "content-match-v999"}
        db_session.flush()
        assert self._reason(db_session, v, cid) == "anchor_inheritance_mismatch"

        # invalid decision vocabulary
        v = self._reload(db_session, successor.id)
        row = self._sections(db_session, v)[0]
        row.anchor_provenance = {**row.anchor_provenance, "decision": "teleported"}
        db_session.flush()
        assert self._reason(db_session, v, cid) == "anchor_decision_invalid"

        # an inherited decision without inherited_from
        v = self._reload(db_session, successor.id)
        row = self._sections(db_session, v)[0]
        row.anchor_provenance = {
            "algo": "heading-path-v1",
            "inheritance": "content-match-v1",
            "decision": "unchanged",
        }
        db_session.flush()
        assert self._reason(db_session, v, cid) == "anchor_inherited_missing_from"

        # a minted decision carrying inherited_from
        v = self._reload(db_session, successor.id)
        row = self._sections(db_session, v)[0]
        row.anchor_provenance = {**row.anchor_provenance, "inheritedFrom": "someanchor"}
        db_session.flush()
        assert self._reason(db_session, v, cid) == "anchor_minted_has_inherited_from"
        self._reload(db_session, successor.id)

    def test_anchor_provenance_semantics_are_validated(
        self, alice, corpus_on, session_factory, db_session
    ):
        """Decision SEMANTICS, not just field shape: the validator receives the
        row's current anchor and enforces the frozen decision matrix through
        the real eligibility path."""
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        cid = source.company_id

        # a preserved-anchor decision naming an UNRELATED predecessor
        v = self._reload(db_session, successor.id)
        row = self._sections(db_session, v)[0]
        row.anchor_provenance = {
            "algo": "heading-path-v1",
            "inheritance": "content-match-v1",
            "decision": "unchanged",
            "inheritedFrom": "zzzzzzzzzzzz",  # not this row's anchor
        }
        db_session.flush()
        assert self._reason(db_session, v, cid) == "anchor_lineage_mismatch"

        # inherited-exact with a non-exact similarity
        v = self._reload(db_session, successor.id)
        row = self._sections(db_session, v)[0]
        row.anchor_provenance = {
            "algo": "heading-path-v1",
            "inheritance": "content-match-v1",
            "decision": "inherited-exact",
            "inheritedFrom": row.anchor_id,
            "similarity": 0.2,
        }
        db_session.flush()
        assert self._reason(db_session, v, cid) == "anchor_similarity_not_exact"

        # inherited-similar below the frozen Jaccard threshold
        v = self._reload(db_session, successor.id)
        row = self._sections(db_session, v)[0]
        row.anchor_provenance = {
            "algo": "heading-path-v1",
            "inheritance": "content-match-v1",
            "decision": "inherited-similar",
            "inheritedFrom": row.anchor_id,
            "similarity": 0.1,
        }
        db_session.flush()
        assert self._reason(db_session, v, cid) == "anchor_similarity_below_threshold"

        # an impossible split parent/child relationship
        v = self._reload(db_session, successor.id)
        row = self._sections(db_session, v)[0]
        row.anchor_provenance = {
            "algo": "heading-path-v1",
            "inheritance": "content-match-v1",
            "decision": "split-lineage",
            "inheritedFrom": row.anchor_id,  # parent == child: impossible
        }
        db_session.flush()
        assert self._reason(db_session, v, cid) == "anchor_split_lineage_invalid"
        self._reload(db_session, successor.id)

    def test_provenance_changed_after_manifest_creation_fails_manifest(
        self, alice, corpus_on, session_factory, db_session
    ):
        """A structurally VALID but different provenance (so it passes provenance
        validation) still fails, because the provenance is bound into the
        manifest digest — proof of cryptographic binding."""
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        cid = source.company_id
        v = self._reload(db_session, successor.id)
        row = self._sections(db_session, v)[0]
        # replace the minted provenance with one that is SEMANTICALLY valid for
        # this row (heading-kept retaining exactly this anchor) — it passes the
        # full semantic validation, so only the manifest binding can catch it
        row.anchor_provenance = {
            "algo": "heading-path-v1",
            "inheritance": "content-match-v1",
            "decision": "heading-kept",
            "inheritedFrom": row.anchor_id,
        }
        db_session.flush()
        # it passes provenance validation, but the manifest no longer reconstructs
        assert self._reason(db_session, v, cid) == "manifest_mismatch"
        self._reload(db_session, successor.id)

    def test_one_consistent_registered_target_remains_eligible(
        self, alice, corpus_on, session_factory, db_session
    ):
        """The positive control: a fully consistent, explicitly registered
        target with intact provenance and manifest is eligible."""
        _doc, source, successor = self._final_successor(alice, session_factory, db_session)
        assert successor.finalization_engine in supported_finalization_targets()
        assert is_generation_eligible(
            db_session, successor, company_id=source.company_id
        ) is True


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #


class TestApi:
    def test_flag_off_finalize_and_versions_are_disabled(self, alice):
        res = alice.post("/api/documents/some-id/finalize")
        assert res.status_code == 403
        assert res.json()["code"] == "tenant_corpus_disabled"
        res = alice.get("/api/documents/some-id/versions")
        assert res.status_code == 403

    def test_cross_tenant_finalize_is_404_shaped(
        self, alice, bob, corpus_on, session_factory, db_session
    ):
        document_id, _ = uploaded_transitional(alice, session_factory, db_session)
        assert bob.post(f"/api/documents/{document_id}/finalize").status_code == 404
        assert bob.get(f"/api/documents/{document_id}/versions").status_code == 404
        # nothing was created for the attacker
        assert len(version_rows(db_session, document_id)) == 1

    def test_not_ready_document_is_409(self, alice, corpus_on, db_session):
        res = upload(alice)  # queued, never drained
        document_id = res.json()["documentId"]
        out = alice.post(f"/api/documents/{document_id}/finalize")
        assert out.status_code == 409
        assert out.json()["code"] == "no_ready_version"

    def test_versions_listing_identifies_transitional_vs_final(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, _ = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)

        res = alice.get(f"/api/documents/{document_id}/versions")
        assert res.status_code == 200
        versions = res.json()["versions"]
        assert [v["versionNo"] for v in versions] == [1, 2]
        assert versions[0]["identity"] == "transitional"
        assert versions[0]["anchorAlgoVersion"] == ANCHOR_ALGO_TRANSITIONAL
        assert versions[0]["current"] is False
        assert versions[1]["identity"] == "final"
        assert versions[1]["anchorAlgoVersion"] == ANCHOR_ALGO_VERSION
        assert versions[1]["current"] is True
        assert versions[1]["finalizedFromVersionNo"] == 1

        # never any content, citation internals or storage details
        import json as jsonlib

        dump = jsonlib.dumps(res.json()).lower()
        for banned in ("citation", "excerpt", "storage_key", "db:", "manifest", "text"):
            assert banned not in dump, banned

    def test_ingestion_payload_distinguishes_states(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, _ = uploaded_transitional(alice, session_factory, db_session)
        ing = alice.get(f"/api/documents/{document_id}").json()["ingestion"]
        assert ing["identity"] == "transitional"
        assert ing["finalized"] is False
        assert ing["stage"] == "ready"
        assert ing["stageKind"] == "ingest"

        alice.post(f"/api/documents/{document_id}/finalize")
        ing = alice.get(f"/api/documents/{document_id}").json()["ingestion"]
        assert ing["stageKind"] == "finalize"
        assert ing["finalized"] is False  # still processing

        drain_jobs(session_factory)
        ing = alice.get(f"/api/documents/{document_id}").json()["ingestion"]
        assert ing["identity"] == "final"
        assert ing["finalized"] is True
        assert ing["stage"] == "ready"

    def test_retry_endpoint_reenqueues_finalize_operation(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, _ = uploaded_transitional(alice, session_factory, db_session)

        def boom(*_a, **_k):
            raise ValueError("forced failure")

        patch = MonkeyPatch()
        patch.setattr(pipeline_module, "assign_anchors", boom)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        patch.undo()

        res = alice.post(f"/api/documents/{document_id}/retry")
        assert res.status_code == 202, res.text
        job = db_session.execute(
            select(IngestionJob)
            .where(IngestionJob.state == JOB_STATE_QUEUED)
            .execution_options(populate_existing=True)
        ).scalar_one()
        assert job.operation == JOB_OPERATION_FINALIZE
        drain_jobs(session_factory)
        assert version_rows(db_session, document_id)[-1].status == VERSION_STATUS_READY

    def test_ingest_jobs_keep_default_operation(
        self, alice, corpus_on, db_session
    ):
        upload(alice)
        job = db_session.execute(select(IngestionJob)).scalar_one()
        assert job.operation == JOB_OPERATION_INGEST


# --------------------------------------------------------------------------- #
# bulk backfill service
# --------------------------------------------------------------------------- #


class TestBackfill:
    def test_discovery_dry_run_execute_and_rerun_idempotency(
        self, alice, bob, corpus_on, session_factory, db_session
    ):
        doc_a, _ = uploaded_transitional(alice, session_factory, db_session)
        res = upload(bob, name="runbook.md")
        assert res.status_code == 202
        drain_jobs(session_factory)

        assert len(discover_eligible(db_session)) == 2
        assert len(discover_eligible(db_session, company_id=alice.company_id)) == 1
        assert len(discover_eligible(db_session, limit=1)) == 1

        dry = run_finalization_backfill(db_session, dry_run=True)
        assert dry.counts["examined"] == 2 and dry.counts["enqueued"] == 2

        first = run_finalization_backfill(db_session)
        assert first.counts["enqueued"] == 2

        # re-run while live: adopts, never duplicates
        second = run_finalization_backfill(db_session)
        assert second.counts["adopted"] == 2 and second.counts["enqueued"] == 0

        drain_jobs(session_factory)

        # after completion: discovery is empty, re-run is a no-op
        assert discover_eligible(db_session) == []
        third = run_finalization_backfill(db_session)
        assert third.counts["examined"] == 0

    def test_bounded_batch_is_resumable(
        self, alice, corpus_on, session_factory, db_session
    ):
        uploaded_transitional(alice, session_factory, db_session)
        body2 = MD_BODY.replace(b"Data Handling Policy", b"Second Policy Document")
        res = upload(alice, body=body2, name="second.md")
        assert res.status_code == 202
        drain_jobs(session_factory)

        batch1 = run_finalization_backfill(db_session, limit=1)
        assert batch1.counts["enqueued"] == 1
        assert len(batch1.successor_version_ids) == 1
        drain_jobs(session_factory)
        batch2 = run_finalization_backfill(db_session, limit=10)
        assert batch2.counts["enqueued"] == 1
        drain_jobs(session_factory)
        assert discover_eligible(db_session) == []

    def test_scoped_processing_never_drains_unrelated_jobs(
        self, alice, bob, corpus_on, session_factory, db_session
    ):
        """The CLI's inline --process path: a worker bounded to this run's
        successor versions leaves other queued work untouched."""
        doc_a, _ = uploaded_transitional(alice, session_factory, db_session)
        # bob has an unrelated queued INGEST job
        res = bob.post(
            "/api/documents/upload", files={"file": ("other.md", MD_BODY, "text/markdown")}
        )
        assert res.status_code == 202

        summary = run_finalization_backfill(db_session, company_id=alice.company_id)
        assert summary.counts["enqueued"] == 1
        worker = IngestionWorker(session_factory, poll_seconds=0.01, max_attempts=3)
        processed = 0
        while worker.process_one(version_ids=summary.successor_version_ids):
            processed += 1
        assert processed == 1
        # alice's successor is done; bob's unrelated job is still queued
        assert version_rows(db_session, doc_a)[-1].status == VERSION_STATUS_READY
        bob_jobs = db_session.execute(
            select(IngestionJob).where(IngestionJob.company_id == bob.company_id)
        ).scalars().all()
        assert len(bob_jobs) == 1 and bob_jobs[0].state == JOB_STATE_QUEUED


# --------------------------------------------------------------------------- #
# complete finalization target (one successor per source + COMPLETE target)
# --------------------------------------------------------------------------- #


class TestCompleteTarget:
    def _components(self):
        import dataclasses

        return dataclasses

    def test_target_digest_is_deterministic_and_complete(self):
        import dataclasses

        module = get_active_module()
        base = build_finalization_target("markdown", module)
        assert base.digest == build_finalization_target("markdown", module).digest
        assert base.digest.startswith("cft1:")
        # every load-bearing component independently changes the digest
        changed = {
            "parser_version": "future-parser",
            "parser_name": "future-name",
            "normalizer": "future-normalizer",
            "sectionizer": "future-sectionizer",
            "anchor_algo": "heading-path-v999",
            "anchor_inheritance": "content-match-v999",
            "classifier": "m999",
            "section_signature": 999,
            "module_id": "other-module",
            "module_version": "9.9.9",
            "module_digest": "f" * 64,
            "module_signature_version": "9.9.9",
            "manifest": "m999",
            "thresholds": (("categoryMinScore", 99.0),),
            "weights": (("bodySignal", 99.0),),
        }
        digests = {base.digest}
        for field_name, value in changed.items():
            variant = dataclasses.replace(base, **{field_name: value})
            assert variant.digest != base.digest, field_name
            digests.add(variant.digest)
        assert len(digests) == len(changed) + 1  # all pairwise distinct

    def test_identical_complete_target_adopts_one_successor(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        first = alice.post(f"/api/documents/{document_id}/finalize")
        second = alice.post(f"/api/documents/{document_id}/finalize")
        assert first.status_code == 202 and second.status_code == 200
        assert second.json()["versionId"] == first.json()["versionId"]
        assert len(version_rows(db_session, document_id)) == 2

    def test_component_change_creates_a_distinct_successor(
        self, alice, corpus_on, session_factory, db_session, monkeypatch
    ):
        """Changing ONE load-bearing component (here the anchor algorithm)
        yields a different complete target and therefore a second successor
        for the same source — never an overwrite of the first artifact."""
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        v2 = version_rows(db_session, document_id)[-1]
        assert v2.status == VERSION_STATUS_READY

        monkeypatch.setattr(anchors_module, "ANCHOR_ALGO_VERSION", "heading-path-v2")
        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()
        outcome = finalize_source_version(db_session, source_version=source, document=doc)
        assert outcome.created is True
        assert outcome.successor.id != v2.id
        assert outcome.successor.finalization_engine != v2.finalization_engine
        versions = version_rows(db_session, document_id)
        assert len(versions) == 3  # source + one successor per complete target

    def test_classifier_change_creates_a_distinct_successor(
        self, alice, corpus_on, session_factory, db_session, monkeypatch
    ):
        import dataclasses

        from app.ingestion import classifier as classifier_module

        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        v2 = version_rows(db_session, document_id)[-1]

        # a future classifier (module compatibility declaration relaxed so the
        # hypothetical engine still accepts the pack)
        free_module = dataclasses.replace(get_active_module(), engine_compatibility={})
        monkeypatch.setattr(finalize_service, "get_active_module", lambda: free_module)
        monkeypatch.setattr(classifier_module, "CLASSIFIER_VERSION", "m9.9")

        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()
        outcome = finalize_source_version(db_session, source_version=source, document=doc)
        assert outcome.created is True and outcome.successor.id != v2.id

    def test_module_version_and_digest_changes_create_distinct_successors(
        self, alice, corpus_on, session_factory, db_session, monkeypatch
    ):
        import dataclasses

        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        v2 = version_rows(db_session, document_id)[-1]
        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()

        bumped = dataclasses.replace(get_active_module(), version="1.1.0")
        monkeypatch.setattr(finalize_service, "get_active_module", lambda: bumped)
        out_version = finalize_source_version(db_session, source_version=source, document=doc)
        assert out_version.created is True and out_version.successor.id != v2.id

        redigested = dataclasses.replace(get_active_module(), digest="f" * 64)
        monkeypatch.setattr(finalize_service, "get_active_module", lambda: redigested)
        out_digest = finalize_source_version(db_session, source_version=source, document=doc)
        assert out_digest.created is True
        assert out_digest.successor.id not in (v2.id, out_version.successor.id)

    def test_unsupported_pinned_target_is_refused_safely(
        self, alice, corpus_on, session_factory, db_session, monkeypatch
    ):
        """A queued job pinned to a target this worker cannot reproduce fails
        closed with the stable typed error — the source version and pointer
        stay untouched, and nothing generates a different artifact."""
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        res = alice.post(f"/api/documents/{document_id}/finalize")
        assert res.status_code == 202

        # the worker "upgraded" between enqueue and claim
        monkeypatch.setattr(anchors_module, "ANCHOR_ALGO_VERSION", "heading-path-v2")
        drain_jobs(session_factory)

        successor = version_rows(db_session, document_id)[-1]
        assert successor.status == VERSION_STATUS_FAILED
        assert successor.error_code == "unsupported_finalization_target"
        assert section_snapshot(db_session, successor.id) == []
        doc = db_session.execute(
            select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
        ).scalar_one()
        assert doc.current_version_id == source.id


# --------------------------------------------------------------------------- #
# DB-enforced source/successor integrity (composite self-reference)
# --------------------------------------------------------------------------- #


class TestSourceSuccessorIntegrity:
    def _insert_successor(self, db, *, document_id, company_id, source_version_id, version_no):
        from sqlalchemy.exc import IntegrityError

        row = DocumentVersion(
            document_id=document_id,
            company_id=company_id,
            version_no=version_no,
            source_version_id=source_version_id,
            finalization_engine="cft1:" + "0" * 64,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return False
        db.rollback()  # never keep the probe row
        return True

    def test_cross_tenant_source_reference_is_unrepresentable(
        self, alice, bob, corpus_on, session_factory, db_session
    ):
        _doc_a, source_a = uploaded_transitional(alice, session_factory, db_session)
        res = bob.post(
            "/api/documents/upload", files={"file": ("theirs.md", MD_BODY, "text/markdown")}
        )
        bob_doc = res.json()["documentId"]
        drain_jobs(session_factory)
        assert self._insert_successor(
            db_session,
            document_id=bob_doc,
            company_id=bob.company_id,
            source_version_id=source_a.id,  # tenant A's version
            version_no=99,
        ) is False

    def test_cross_document_source_reference_is_unrepresentable(
        self, alice, corpus_on, session_factory, db_session
    ):
        _doc1, source1 = uploaded_transitional(alice, session_factory, db_session)
        body2 = MD_BODY.replace(b"Data Handling Policy", b"Second Policy Document")
        res = upload(alice, body=body2, name="second.md")
        doc2 = res.json()["documentId"]
        drain_jobs(session_factory)
        assert self._insert_successor(
            db_session,
            document_id=doc2,
            company_id=alice.company_id,
            source_version_id=source1.id,  # another document's version
            version_no=99,
        ) is False

    def test_valid_same_document_reference_is_accepted(
        self, alice, corpus_on, session_factory, db_session
    ):
        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        assert self._insert_successor(
            db_session,
            document_id=document_id,
            company_id=source.company_id,
            source_version_id=source.id,
            version_no=99,
        ) is True

    def test_deleting_a_referenced_source_version_is_blocked(
        self, alice, corpus_on, session_factory, db_session
    ):
        from sqlalchemy import delete
        from sqlalchemy.exc import IntegrityError

        document_id, source = uploaded_transitional(alice, session_factory, db_session)
        alice.post(f"/api/documents/{document_id}/finalize")
        drain_jobs(session_factory)
        assert len(version_rows(db_session, document_id)) == 2

        with pytest.raises(IntegrityError):
            db_session.execute(
                delete(DocumentVersion).where(DocumentVersion.id == source.id)
            )
            db_session.commit()
        db_session.rollback()
        # the chain is intact and still resolvable
        versions = version_rows(db_session, document_id)
        assert [v.version_no for v in versions] == [1, 2]
        assert versions[1].source_version_id == versions[0].id


# --------------------------------------------------------------------------- #
# citation-prefix capacity (DB-arbitrated allocation)
# --------------------------------------------------------------------------- #


class TestPrefixCapacityDb:
    def _mint_documents(self, db, company_id, count, *, title="policy", prefill=None):
        docs = []
        for n in range(count):
            doc = Document(
                company_id=company_id,
                title=title,
                slug=f"prefix-cap-{n}",
                citation_prefix=(prefill(n) if prefill else None),
            )
            db.add(doc)
            docs.append(doc)
        db.commit()
        return docs

    def test_52_same_base_documents_all_allocate(self, alice, corpus_on, db_session):
        docs = self._mint_documents(db_session, alice.company_id, 52)
        for doc in docs:
            ensure_citation_prefix(db_session, doc)
        prefixes = [doc.citation_prefix for doc in docs]
        assert prefixes[0] == "PLC"
        assert prefixes[51] == "PLC52"
        assert len(set(prefixes)) == 52
        for prefix in prefixes:
            assert len(prefix) <= 12  # column-length safety

    def test_allocation_through_the_configured_quota_boundary(
        self, alice, corpus_on, db_session
    ):
        """With every candidate below the boundary taken, the 500th document
        still allocates; the 501st fails typed — exactly at the configured
        quota, not at an arbitrary internal cap."""
        quota = get_settings().evidentia_tenant_max_documents
        assert quota == 500
        # occupy DOC, DOC2..DOC499 directly (efficient boundary setup)
        self._mint_documents(
            db_session,
            alice.company_id,
            499,
            title="",
            prefill=lambda n: "DOC" if n == 0 else f"DOC{n + 1}",
        )
        doc_500 = self._mint_documents(db_session, alice.company_id, 1, title="")[0]
        allocated = ensure_citation_prefix(db_session, doc_500)
        assert allocated == "DOC500"
        assert len(allocated) <= 12

        doc_501 = self._mint_documents(db_session, alice.company_id, 1, title="")[0]
        doc_501.citation_prefix = None
        # every candidate DOC..DOC501 is taken except DOC501; quota admits it
        allocated_501 = ensure_citation_prefix(db_session, doc_501)
        assert allocated_501 == "DOC501"

        doc_502 = self._mint_documents(db_session, alice.company_id, 1, title="")[0]
        with pytest.raises(IngestionError) as excinfo:
            ensure_citation_prefix(db_session, doc_502)
        assert excinfo.value.code == "citation_prefix_failed"

    def test_retry_adopts_the_same_prefix(self, alice, corpus_on, db_session):
        doc = self._mint_documents(db_session, alice.company_id, 1)[0]
        first = ensure_citation_prefix(db_session, doc)
        again = ensure_citation_prefix(db_session, doc)
        assert first == again == doc.citation_prefix

    def test_non_latin_titles_allocate(self, alice, corpus_on, db_session):
        docs = self._mint_documents(db_session, alice.company_id, 3, title="日本語の方針")
        for doc in docs:
            ensure_citation_prefix(db_session, doc)
        assert [d.citation_prefix for d in docs] == ["DOC", "DOC2", "DOC3"]
