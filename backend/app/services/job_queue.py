"""JobQueue — the seam ingestion work rides through (M1 enqueue + M2 worker ops).

Mirrors the `RateLimitStore` / `BlobStore` precedent: a Protocol with a
DB-table-backed single-instance implementation now, a shared queue (Redis/RQ)
later with zero call-site changes. Durability, retry accounting and
observability come from the `ingestion_jobs` table, not from the process.

M2 adds the worker half, with the binding requirements recorded on the
`IngestionJob` model:

* **Tenant-fair claiming** — the claim considers one candidate per tenant (the
  tenant's oldest queued job) and serves tenants round-robin, so one tenant
  bulk-uploading hundreds of documents cannot starve another tenant's single
  upload. Never pure FIFO.
* **Claim-time attempt increment** — a poison job that kills the worker
  process outright must still hit the attempts cap instead of being requeued
  forever by the stale sweep.
* **Ownership transitions are atomic conditional UPDATEs** (``WHERE state =
  <expected>``): two workers racing for one job get exactly one winner on both
  PostgreSQL (row lock on UPDATE) and SQLite (single-writer lock), with no
  check-then-write window. Completed/terminally-failed jobs can never be
  reclaimed because every transition re-checks the current state.
* **Stale recovery** — `running` rows whose heartbeat is older than the
  threshold are requeued (attempts below the cap) or terminally failed
  (at the cap). Runs at worker startup and periodically.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Collection, List, Optional, Protocol, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.db_models import (
    JOB_OPERATION_INGEST,
    JOB_STATE_FAILED,
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    JOB_STATE_SUCCEEDED,
    IngestionJob,
)

# Bounded, user-safe job error text (full tracebacks belong in server logs).
_MAX_JOB_ERROR_CHARS = 500


class JobQueue(Protocol):
    """Queue seam for ingestion jobs. Callers own the transaction: every
    method flushes but never commits, so the caller decides the commit point
    (the worker commits a claim immediately to make ownership durable)."""

    def enqueue(
        self,
        db: Session,
        *,
        company_id: str,
        document_id: str,
        version_id: str,
        operation: str = JOB_OPERATION_INGEST,
    ) -> IngestionJob:  # pragma: no cover
        """Queue work for a document version and return the job row.

        `operation` is the explicit typed discriminator ("ingest" | M3
        "finalize"). Idempotent per version: a version that already has a
        live (queued or running) job gets that job back instead of a
        duplicate.
        """
        ...

    def claim(
        self,
        db: Session,
        *,
        now: Optional[datetime] = None,
        version_ids: Optional[Collection[str]] = None,
    ) -> Optional[IngestionJob]:  # pragma: no cover
        """Atomically claim the next queued job (tenant-fair), moving it
        queued -> running and incrementing `attempts`. None when idle.
        ``version_ids`` restricts claiming to jobs for those versions (used by
        bounded inline processing so a CLI run never drains unrelated work)."""
        ...

    def heartbeat(self, db: Session, job_id: str, *, now: Optional[datetime] = None) -> bool:  # pragma: no cover
        """Refresh the running job's liveness. False when the job is no longer
        running (ownership lost — the holder must stop working on it)."""
        ...

    def complete(self, db: Session, job_id: str) -> bool:  # pragma: no cover
        """running -> succeeded. False when the job was not running."""
        ...

    def fail(
        self, db: Session, job_id: str, *, error: str, retryable: bool, max_attempts: int
    ) -> str:  # pragma: no cover
        """running -> queued (retryable, attempts below cap) or failed.
        Returns the resulting state."""
        ...

    def recover_stale(
        self, db: Session, *, stale_before: datetime, max_attempts: int, now: Optional[datetime] = None
    ) -> List[IngestionJob]:  # pragma: no cover
        """Requeue (or terminally fail, at the attempts cap) `running` jobs
        whose heartbeat predates `stale_before`. Returns the touched rows."""
        ...


class DatabaseJobQueue:
    """v1 implementation: one `ingestion_jobs` row per unit of work.

    Enqueue idempotency is enforced at two levels. The pre-select handles the
    common repeat call cheaply; the partial unique index
    `uq_ingestion_jobs_live_version` (one row per version while queued/running)
    is the authority when two sessions race past the pre-select. The insert
    runs inside a SAVEPOINT so a losing racer's IntegrityError rolls back only
    the job insert — never the caller's outer transaction — and the loser then
    re-selects and returns the surviving live job.

    The round-robin cursor (`_rr_cursor`) is in-process state, consistent with
    the documented single-instance posture: it orders *which tenant is served
    next* and resets on restart, while correctness (single ownership, attempt
    accounting) never depends on it.
    """

    def __init__(self) -> None:
        self._rr_cursor: str = ""

    # -- enqueue (M1) -------------------------------------------------------- #

    def _live_job(self, db: Session, company_id: str, version_id: str) -> Optional[IngestionJob]:
        return db.execute(
            select(IngestionJob).where(
                IngestionJob.version_id == version_id,
                IngestionJob.company_id == company_id,
                IngestionJob.state.in_((JOB_STATE_QUEUED, JOB_STATE_RUNNING)),
            )
        ).scalars().first()

    def enqueue(
        self,
        db: Session,
        *,
        company_id: str,
        document_id: str,
        version_id: str,
        operation: str = JOB_OPERATION_INGEST,
    ) -> IngestionJob:
        existing = self._live_job(db, company_id, version_id)
        if existing is not None:
            return existing
        job = IngestionJob(
            company_id=company_id,
            document_id=document_id,
            version_id=version_id,
            state=JOB_STATE_QUEUED,
            operation=operation,
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

    # -- claim (M2) ----------------------------------------------------------- #

    def _queued_candidates(
        self, db: Session, version_ids: Optional[Collection[str]] = None
    ) -> List[Tuple[str, str]]:
        """One candidate per tenant: (company_id, job_id of that tenant's
        oldest queued job — created_at then id for a total, deterministic
        order). ``version_ids`` bounds the candidate set for scoped runs."""
        query = (
            select(
                IngestionJob.company_id,
                IngestionJob.id,
                IngestionJob.created_at,
            )
            .where(IngestionJob.state == JOB_STATE_QUEUED)
            .order_by(IngestionJob.created_at.asc(), IngestionJob.id.asc())
        )
        if version_ids is not None:
            query = query.where(IngestionJob.version_id.in_(list(version_ids)))
        rows = db.execute(query).all()
        oldest_per_company: dict[str, str] = {}
        for company_id, job_id, _created in rows:
            oldest_per_company.setdefault(company_id, job_id)
        return sorted(oldest_per_company.items())

    def claim(
        self,
        db: Session,
        *,
        now: Optional[datetime] = None,
        version_ids: Optional[Collection[str]] = None,
    ) -> Optional[IngestionJob]:
        now = now or datetime.utcnow()
        candidates = self._queued_candidates(db, version_ids)
        if not candidates:
            return None

        # Round-robin: serve the first tenant strictly after the cursor in the
        # stable company ordering, wrapping — so tenant A's bulk backlog and
        # tenant B's single job alternate instead of A monopolizing workers.
        after = [c for c in candidates if c[0] > self._rr_cursor]
        ordered = after + [c for c in candidates if c[0] <= self._rr_cursor]

        for company_id, job_id in ordered:
            claimed = db.execute(
                update(IngestionJob)
                .where(IngestionJob.id == job_id, IngestionJob.state == JOB_STATE_QUEUED)
                .values(
                    state=JOB_STATE_RUNNING,
                    attempts=IngestionJob.attempts + 1,  # claim-time increment
                    heartbeat_at=now,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount == 1:
                self._rr_cursor = company_id
                db.flush()
                return db.execute(
                    select(IngestionJob)
                    .where(IngestionJob.id == job_id)
                    .execution_options(populate_existing=True)
                ).scalar_one()
            # Another worker won this row; try the next tenant's candidate.
        return None

    # -- running-job lifecycle (M2) ------------------------------------------ #

    def heartbeat(self, db: Session, job_id: str, *, now: Optional[datetime] = None) -> bool:
        now = now or datetime.utcnow()
        result = db.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.state == JOB_STATE_RUNNING)
            .values(heartbeat_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def complete(self, db: Session, job_id: str) -> bool:
        now = datetime.utcnow()
        result = db.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.state == JOB_STATE_RUNNING)
            .values(state=JOB_STATE_SUCCEEDED, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def fail(
        self, db: Session, job_id: str, *, error: str, retryable: bool, max_attempts: int
    ) -> str:
        now = datetime.utcnow()
        job = db.execute(
            select(IngestionJob)
            .where(IngestionJob.id == job_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if job is None or job.state != JOB_STATE_RUNNING:
            return job.state if job is not None else JOB_STATE_FAILED

        next_state = (
            JOB_STATE_QUEUED if retryable and job.attempts < max_attempts else JOB_STATE_FAILED
        )
        result = db.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.state == JOB_STATE_RUNNING)
            .values(
                state=next_state,
                last_error=(error or "")[:_MAX_JOB_ERROR_CHARS],
                heartbeat_at=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        db.flush()
        return next_state if result.rowcount == 1 else JOB_STATE_FAILED

    def recover_stale(
        self,
        db: Session,
        *,
        stale_before: datetime,
        max_attempts: int,
        now: Optional[datetime] = None,
    ) -> List[IngestionJob]:
        now = now or datetime.utcnow()
        stale = db.execute(
            select(IngestionJob)
            .where(
                IngestionJob.state == JOB_STATE_RUNNING,
                IngestionJob.heartbeat_at.isnot(None),
                IngestionJob.heartbeat_at < stale_before,
            )
            .execution_options(populate_existing=True)
        ).scalars().all()

        touched: List[IngestionJob] = []
        for job in stale:
            # Attempts were already incremented when the dead holder claimed
            # the job, so the cap check needs no further increment here.
            next_state = JOB_STATE_QUEUED if job.attempts < max_attempts else JOB_STATE_FAILED
            values = {
                "state": next_state,
                "heartbeat_at": None,
                "updated_at": now,
            }
            if next_state == JOB_STATE_FAILED:
                values["last_error"] = "stale_abandoned: worker stopped heartbeating"
            result = db.execute(
                update(IngestionJob)
                .where(IngestionJob.id == job.id, IngestionJob.state == JOB_STATE_RUNNING)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 1:
                touched.append(job)
        db.flush()
        return touched


def get_job_queue() -> JobQueue:
    """The configured job queue. v1: always the DB-backed implementation."""
    return DatabaseJobQueue()
