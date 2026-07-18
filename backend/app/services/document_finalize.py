"""M3 finalization trigger: transitional version -> immutable final successor.

Implements the binding M2→M3 lifecycle contract (DECISIONS.md 2026-07-16):

* only versions stamped ``anchor_algo_version = "pre-m3-transitional"`` are
  eligible for this upgrade path, and they are **immutable** — finalization
  never touches the source row, its sections, its transitional ids or its
  manifest;
* finalization creates a NEW ``document_versions`` row (version N+1) that
  reuses the retained source blob (``source_version_id`` — no byte copy) and
  is processed by the worker through the complete M3 path;
* at most one successor exists per (source version, engine target) — the
  unique index ``uq_document_versions_source_engine`` is the authority when
  two triggers race — and at most one live job exists per successor
  (``uq_ingestion_jobs_live_version``), so retries adopt instead of
  duplicating;
* a failed finalization never moves ``documents.current_version_id`` (the
  guarded single flip site only runs on the ready path).

Everything is tenant-scoped: a source version belonging to another tenant is
indistinguishable from one that does not exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ingestion.finalization_target import (
    CompleteFinalizationTarget,
    build_finalization_target,
)
from app.ingestion.pipeline import resolve_source_format
from app.ingestion.sectionizer import ANCHOR_ALGO_TRANSITIONAL
from app.modules.loader import ModuleValidationError, get_active_module
from app.models.db_models import (
    JOB_OPERATION_FINALIZE,
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    VERSION_STATUS_FAILED,
    VERSION_STATUS_PENDING,
    VERSION_STATUS_READY,
    Document,
    DocumentVersion,
    IngestionJob,
)
from app.services.job_queue import JobQueue, get_job_queue

logger = logging.getLogger("evidentia.finalize")

# Stable, user-safe rejection codes (the API maps them to status codes).
CODE_NOT_FINALIZABLE = "not_finalizable"
CODE_ALREADY_FINAL = "already_final"
CODE_NO_READY_VERSION = "no_ready_version"
CODE_ENGINE_UNAVAILABLE = "finalization_unavailable"


def _current_target(document: Document) -> CompleteFinalizationTarget:
    """The COMPLETE finalization target captured at trigger/enqueue time —
    the single builder shared with worker verification and eligibility. An
    invalid or engine-incompatible module pack fails the trigger closed."""
    try:
        return build_finalization_target(resolve_source_format(document), get_active_module())
    except ModuleValidationError as exc:
        logger.error("finalization target unavailable: %s", exc)
        raise FinalizeRejected(
            503, CODE_ENGINE_UNAVAILABLE, "Document finalization is temporarily unavailable."
        ) from None


class FinalizeRejected(Exception):
    """A typed, user-safe rejection. Never carries document text, storage
    internals or a traceback."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class FinalizeOutcome:
    document: Document
    source_version: DocumentVersion
    successor: DocumentVersion
    created: bool          # a new successor row was created by this call
    adopted: bool = False  # an existing live successor/job was adopted
    already_final: bool = False  # the successor is already ready
    retried: bool = False  # a failed successor was reset and re-enqueued


def _successor_for(
    db: Session, *, source_version_id: str, company_id: str, engine: str
) -> Optional[DocumentVersion]:
    return db.execute(
        select(DocumentVersion).where(
            DocumentVersion.source_version_id == source_version_id,
            DocumentVersion.company_id == company_id,
            DocumentVersion.finalization_engine == engine,
        )
    ).scalar_one_or_none()


def _has_live_job(db: Session, version_id: str) -> bool:
    return (
        db.execute(
            select(IngestionJob.id)
            .where(
                IngestionJob.version_id == version_id,
                IngestionJob.state.in_((JOB_STATE_QUEUED, JOB_STATE_RUNNING)),
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _latest_version_no(db: Session, document_id: str, company_id: str) -> int:
    latest = db.execute(
        select(DocumentVersion.version_no)
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.company_id == company_id,
        )
        .order_by(DocumentVersion.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()
    return latest or 0


def finalize_source_version(
    db: Session,
    *,
    source_version: DocumentVersion,
    document: Document,
    user_id: Optional[str] = None,
    job_queue: Optional[JobQueue] = None,
) -> FinalizeOutcome:
    """Create-or-adopt the finalization successor for one eligible source
    version and ensure exactly one live finalize job exists for it.

    Idempotent and race-safe: repeated calls (and concurrent calls, on
    PostgreSQL) converge on the same successor row and the same live job.
    Commits on success.
    """
    jobs = job_queue or get_job_queue()
    company_id = document.company_id

    if source_version.status != VERSION_STATUS_READY:
        raise FinalizeRejected(
            409, CODE_NOT_FINALIZABLE, "Only a fully processed document version can be finalized."
        )
    if source_version.anchor_algo_version != ANCHOR_ALGO_TRANSITIONAL:
        raise FinalizeRejected(
            409, CODE_ALREADY_FINAL, "This document version is already citation-ready."
        )

    # Capture the COMPLETE target NOW (trigger time). The successor pins this
    # digest; the worker refuses to process it under any other target.
    engine = _current_target(document).digest

    # Adopt an existing successor for THIS complete target (idempotency + the
    # retry path). A successor produced for a different complete target never
    # matches — it is a different artifact.
    existing = _successor_for(
        db, source_version_id=source_version.id, company_id=company_id, engine=engine
    )
    if existing is not None:
        return _adopt_successor(db, document, source_version, existing, jobs)

    successor = DocumentVersion(
        document_id=document.id,
        company_id=company_id,
        version_no=_latest_version_no(db, document.id, company_id) + 1,
        content_sha256=source_version.content_sha256,  # same source bytes
        source_version_id=source_version.id,
        finalization_engine=engine,
        status=VERSION_STATUS_PENDING,
        created_by=user_id,
    )
    try:
        with db.begin_nested():
            db.add(successor)
            db.flush()
    except IntegrityError:
        # Lost a race on (source_version_id, finalization_engine) or on
        # (document_id, version_no): a concurrent trigger created the
        # successor. The savepoint rollback discarded only our insert; adopt
        # the survivor.
        db.expire_all()
        survivor = _successor_for(
            db, source_version_id=source_version.id, company_id=company_id, engine=engine
        )
        if survivor is None:
            raise
        return _adopt_successor(db, document, source_version, survivor, jobs)

    jobs.enqueue(
        db,
        company_id=company_id,
        document_id=document.id,
        version_id=successor.id,
        operation=JOB_OPERATION_FINALIZE,
    )
    db.commit()
    logger.info(
        "finalization enqueued company=%s document=%s source_version=%s successor=%s version_no=%d",
        company_id, document.id, source_version.id, successor.id, successor.version_no,
    )
    return FinalizeOutcome(
        document=document, source_version=source_version, successor=successor, created=True
    )


def _adopt_successor(
    db: Session,
    document: Document,
    source_version: DocumentVersion,
    successor: DocumentVersion,
    jobs: JobQueue,
) -> FinalizeOutcome:
    if successor.status == VERSION_STATUS_READY:
        db.commit()  # nothing written; release the transaction
        return FinalizeOutcome(
            document=document,
            source_version=source_version,
            successor=successor,
            created=False,
            already_final=True,
        )
    retried = False
    if successor.status == VERSION_STATUS_FAILED and not _has_live_job(db, successor.id):
        # A terminally failed finalization: reuse the immutable successor row
        # (never a second successor — the unique index forbids it) and give it
        # a fresh job.
        successor.status = VERSION_STATUS_PENDING
        successor.error_code = None
        successor.error_detail = None
        retried = True
    jobs.enqueue(
        db,
        company_id=document.company_id,
        document_id=document.id,
        version_id=successor.id,
        operation=JOB_OPERATION_FINALIZE,
    )
    db.commit()
    return FinalizeOutcome(
        document=document,
        source_version=source_version,
        successor=successor,
        created=False,
        adopted=True,
        retried=retried,
    )


def finalize_document(
    db: Session,
    *,
    document: Document,
    user_id: Optional[str] = None,
    job_queue: Optional[JobQueue] = None,
) -> FinalizeOutcome:
    """Finalize a document's CURRENT version (the API-facing single-document
    trigger). The current version must be a ready transitional version."""
    if not document.current_version_id:
        raise FinalizeRejected(
            409, CODE_NO_READY_VERSION, "This document has no processed version to finalize."
        )
    source = db.execute(
        select(DocumentVersion).where(
            DocumentVersion.id == document.current_version_id,
            DocumentVersion.company_id == document.company_id,
        )
    ).scalar_one_or_none()
    if source is None:
        raise FinalizeRejected(
            409, CODE_NO_READY_VERSION, "This document has no processed version to finalize."
        )
    return finalize_source_version(
        db, source_version=source, document=document, user_id=user_id, job_queue=job_queue
    )


# --------------------------------------------------------------------------- #
# bulk discovery / backfill (CLI)
# --------------------------------------------------------------------------- #


@dataclass
class BackfillSummary:
    examined: int = 0
    enqueued: List[str] = field(default_factory=list)        # source version ids
    adopted: List[str] = field(default_factory=list)
    retried: List[str] = field(default_factory=list)
    already_final: List[str] = field(default_factory=list)
    skipped_ineligible: List[str] = field(default_factory=list)
    # Successor version ids THIS run enqueued/adopted/retried — the exact
    # work set an inline `--process` may drain (never the global queue).
    successor_version_ids: List[str] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {
            "examined": self.examined,
            "enqueued": len(self.enqueued),
            "adopted": len(self.adopted),
            "retried": len(self.retried),
            "alreadyFinal": len(self.already_final),
            "skippedIneligible": len(self.skipped_ineligible),
        }


def discover_eligible(
    db: Session,
    *,
    company_id: Optional[str] = None,
    document_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Tuple[Document, DocumentVersion]]:
    """Eligible finalization targets: documents whose CURRENT version is a
    ready `pre-m3-transitional` version. Deterministic order (created_at, id)
    so bounded batches are resumable."""
    query = (
        select(Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
        .where(
            Document.deleted_at.is_(None),
            DocumentVersion.status == VERSION_STATUS_READY,
            DocumentVersion.anchor_algo_version == ANCHOR_ALGO_TRANSITIONAL,
        )
        .order_by(Document.created_at.asc(), Document.id.asc())
    )
    if company_id:
        query = query.where(Document.company_id == company_id)
    if document_id:
        query = query.where(Document.id == document_id)
    if limit:
        query = query.limit(limit)
    return [(doc, version) for doc, version in db.execute(query).all()]


def run_finalization_backfill(
    db: Session,
    *,
    company_id: Optional[str] = None,
    document_id: Optional[str] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    job_queue: Optional[JobQueue] = None,
) -> BackfillSummary:
    """Discover eligible transitional versions and ensure each has exactly one
    finalization successor + live job. Idempotent: re-running is a no-op for
    completed or live targets. Logs ids and counts only, never content."""
    summary = BackfillSummary()
    targets = discover_eligible(
        db, company_id=company_id, document_id=document_id, limit=limit
    )
    for document, source in targets:
        summary.examined += 1
        if dry_run:
            try:
                engine = _current_target(document).digest
            except FinalizeRejected:
                summary.skipped_ineligible.append(source.id)
                continue
            existing = _successor_for(
                db, source_version_id=source.id, company_id=document.company_id, engine=engine
            )
            if existing is None:
                summary.enqueued.append(source.id)
            elif existing.status == VERSION_STATUS_READY:
                summary.already_final.append(source.id)
            else:
                summary.adopted.append(source.id)
            continue
        try:
            outcome = finalize_source_version(
                db, source_version=source, document=document, job_queue=job_queue
            )
        except FinalizeRejected as exc:
            db.rollback()
            summary.skipped_ineligible.append(source.id)
            logger.info(
                "finalization skipped company=%s document=%s source_version=%s code=%s",
                document.company_id, document.id, source.id, exc.code,
            )
            continue
        if outcome.already_final:
            summary.already_final.append(source.id)
        elif outcome.retried:
            summary.retried.append(source.id)
            summary.successor_version_ids.append(outcome.successor.id)
        elif outcome.adopted:
            summary.adopted.append(source.id)
            summary.successor_version_ids.append(outcome.successor.id)
        else:
            summary.enqueued.append(source.id)
            summary.successor_version_ids.append(outcome.successor.id)
    logger.info("finalization backfill summary %s", summary.counts)
    return summary
