"""JobQueue — the seam ingestion work rides through (M1).

Mirrors the `RateLimitStore` / `BlobStore` precedent: a Protocol with a
DB-table-backed single-instance implementation now, a shared queue (Redis/RQ)
later with zero call-site changes. Durability, retry accounting and
observability come from the `ingestion_jobs` table, not from the process.

M1 ships only the enqueue half — the worker that claims and executes jobs is
the M2 milestone, and its binding requirements are recorded on the
`IngestionJob` model: tenant-fair claiming (round-robin across tenants, never
pure FIFO), `attempts` incremented at claim time (a poison job that kills the
worker must still hit the cap), and a startup sweep that requeues stale
`running` rows via `heartbeat_at`. The Protocol will grow those methods
additively in M2; consumers written against it today never change.
"""

from __future__ import annotations

from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.db_models import JOB_STATE_QUEUED, JOB_STATE_RUNNING, IngestionJob


class JobQueue(Protocol):
    """Enqueue seam for ingestion jobs. Callers own the transaction."""

    def enqueue(self, db: Session, *, company_id: str, document_id: str, version_id: str) -> IngestionJob:  # pragma: no cover
        """Queue ingestion work for a document version and return the job row.

        Idempotent per version: a version that already has a live (queued or
        running) job gets that job back instead of a duplicate.
        """
        ...


class DatabaseJobQueue:
    """v1 implementation: one `ingestion_jobs` row per unit of work.

    Idempotency is enforced at two levels. The pre-select handles the common
    repeat call cheaply; the partial unique index
    `uq_ingestion_jobs_live_version` (one row per version while queued/running)
    is the authority when two sessions race past the pre-select. The insert
    runs inside a SAVEPOINT so a losing racer's IntegrityError rolls back only
    the job insert — never the caller's outer transaction — and the loser then
    re-selects and returns the surviving live job.
    """

    def _live_job(self, db: Session, company_id: str, version_id: str) -> Optional[IngestionJob]:
        return db.execute(
            select(IngestionJob).where(
                IngestionJob.version_id == version_id,
                IngestionJob.company_id == company_id,
                IngestionJob.state.in_((JOB_STATE_QUEUED, JOB_STATE_RUNNING)),
            )
        ).scalars().first()

    def enqueue(self, db: Session, *, company_id: str, document_id: str, version_id: str) -> IngestionJob:
        existing = self._live_job(db, company_id, version_id)
        if existing is not None:
            return existing
        job = IngestionJob(
            company_id=company_id,
            document_id=document_id,
            version_id=version_id,
            state=JOB_STATE_QUEUED,
        )
        try:
            with db.begin_nested():
                db.add(job)
                db.flush()
        except IntegrityError:
            # Lost the enqueue race: a concurrent session inserted the live
            # job between our pre-select and our flush. The savepoint rollback
            # discarded only our insert; adopt the survivor. Anything else
            # (survivor genuinely absent) is a real integrity failure.
            survivor = self._live_job(db, company_id, version_id)
            if survivor is None:
                raise
            return survivor
        return job


def get_job_queue() -> JobQueue:
    """The configured job queue. v1: always the DB-backed implementation."""
    return DatabaseJobQueue()
