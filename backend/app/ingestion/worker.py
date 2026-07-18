"""In-process ingestion worker (M2).

The documented single-instance deployment shape: a small pool of daemon
threads inside the FastAPI process, fed exclusively through the `JobQueue`
seam. A shared queue (Redis/RQ) later replaces the queue implementation, not
this loop's call sites.

Lifecycle contract:

* started from the application startup hook ONLY when
  ``EVIDENTIA_TENANT_CORPUS_ENABLED`` and the database are both enabled —
  otherwise the worker is never constructed (flag off = inert, byte-for-byte
  today's behavior);
* `start()` is idempotent (a second call is a no-op), so Uvicorn dev-reload
  re-imports and repeated TestClient lifespans cannot stack duplicate pools;
* startup first sweeps stale `running` jobs (crash recovery), then polls by
  waiting on an Event — interruptible sleep, no busy spin;
* graceful shutdown: `stop()` sets the event and joins every thread;
* claims/heartbeats/completions go through the queue's atomic conditional
  updates; a lost heartbeat (ownership stolen by the stale sweep) aborts the
  holder's work;
* expected parser/service failures are classified retryable vs terminal
  (typed `IngestionError`); unexpected exceptions are logged with traceback
  (never document text) and retried up to the attempts cap, so a poison
  document can never loop forever.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.errors import ERROR_INTERNAL, ERROR_STALE_ABANDONED, IngestionError
from app.ingestion.pipeline import (
    OwnershipLost,
    mark_version_failed,
    process_finalization,
    process_version,
)
from app.models.db_models import JOB_OPERATION_FINALIZE, JOB_STATE_FAILED, IngestionJob
from app.services.job_queue import DatabaseJobQueue, JobQueue

logger = logging.getLogger("evidentia.ingestion.worker")

SessionFactory = Callable[[], Session]


class IngestionWorker:
    """Bounded worker pool over the durable job table."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        queue: Optional[JobQueue] = None,
        worker_count: Optional[int] = None,
        poll_seconds: Optional[float] = None,
        stale_seconds: Optional[int] = None,
        max_attempts: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._session_factory = session_factory
        self._queue = queue or DatabaseJobQueue()
        self._worker_count = max(1, worker_count or settings.evidentia_ingestion_worker_count)
        self._poll_seconds = poll_seconds or settings.evidentia_ingestion_poll_seconds
        self._stale_seconds = stale_seconds or settings.evidentia_ingestion_stale_seconds
        self._max_attempts = max_attempts or settings.evidentia_ingestion_max_attempts
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------------ #

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def start(self) -> None:
        """Idempotent: never stacks a second pool onto a live one."""
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._recover_stale_once()
            self._threads = [
                threading.Thread(
                    target=self._run_loop,
                    name=f"evidentia-ingestion-{i}",
                    daemon=True,
                )
                for i in range(self._worker_count)
            ]
            for thread in self._threads:
                thread.start()
            logger.info(
                "ingestion worker started threads=%d poll=%.1fs stale=%ds max_attempts=%d",
                self._worker_count, self._poll_seconds, self._stale_seconds, self._max_attempts,
            )

    def stop(self, timeout: float = 10.0) -> None:
        with self._lock:
            if not self._threads:
                return
            self._stop.set()
            for thread in self._threads:
                thread.join(timeout=timeout)
            self._threads = []
            logger.info("ingestion worker stopped")

    # -- loop ------------------------------------------------------------------ #

    def _run_loop(self) -> None:
        last_sweep = time.monotonic()
        while not self._stop.is_set():
            worked = False
            try:
                worked = self.process_one()
            except Exception:  # noqa: BLE001 - the loop itself must survive
                logger.exception("ingestion worker loop error")
            # periodic stale sweep (cheap; single-instance posture)
            if time.monotonic() - last_sweep >= self._stale_seconds:
                self._recover_stale_once()
                last_sweep = time.monotonic()
            if not worked:
                # Interruptible wait — no busy spin, prompt shutdown.
                self._stop.wait(self._poll_seconds)

    def _recover_stale_once(self) -> None:
        db = self._session_factory()
        try:
            stale_before = datetime.utcnow() - timedelta(seconds=self._stale_seconds)
            touched = self._queue.recover_stale(
                db, stale_before=stale_before, max_attempts=self._max_attempts
            )
            db.commit()
            for job in touched:
                logger.warning(
                    "stale job recovered job=%s company=%s version=%s attempts=%d state=%s",
                    job.id, job.company_id, job.version_id, job.attempts, job.state,
                )
                if job.state == JOB_STATE_FAILED:
                    mark_version_failed(
                        db,
                        version_id=job.version_id,
                        company_id=job.company_id,
                        error=IngestionError(
                            ERROR_STALE_ABANDONED,
                            "Processing was interrupted repeatedly and has been stopped.",
                        ),
                    )
        except Exception:  # noqa: BLE001 - sweep failure must not kill the loop
            db.rollback()
            logger.exception("stale-job recovery failed")
        finally:
            db.close()

    # -- one unit of work -------------------------------------------------------- #

    def process_one(self, version_ids=None) -> bool:
        """Claim and process a single job. Returns True when a job was found.
        Public so tests (and the smoke harness) can drive the worker
        deterministically without threads. ``version_ids`` restricts claiming
        to jobs for those versions (bounded inline CLI processing — never the
        global queue)."""
        db = self._session_factory()
        try:
            job = self._queue.claim(db, version_ids=version_ids)
            if job is None:
                return False
            db.commit()  # ownership durable before any work
            self._execute(db, job)
            return True
        finally:
            db.close()

    def _execute(self, db: Session, job: IngestionJob) -> None:
        job_id, company_id, version_id = job.id, job.company_id, job.version_id
        operation = job.operation
        attempt = job.attempts
        started = time.perf_counter()
        logger.info(
            "ingestion claimed job=%s operation=%s company=%s document=%s version=%s attempt=%d",
            job_id, operation, company_id, job.document_id, version_id, attempt,
        )

        def _stage_heartbeat() -> bool:
            """Refresh ownership between finalization stages; False aborts the
            holder (the stale sweep reassigned the job)."""
            alive = self._queue.heartbeat(db, job_id)
            db.commit()
            return alive

        try:
            if not self._queue.heartbeat(db, job_id):
                db.rollback()
                return  # ownership lost to the stale sweep; do no work
            db.commit()
            if operation == JOB_OPERATION_FINALIZE:
                process_finalization(
                    db,
                    version_id=version_id,
                    company_id=company_id,
                    heartbeat=_stage_heartbeat,
                )
            else:
                process_version(db, version_id=version_id, company_id=company_id)
        except OwnershipLost:
            db.rollback()
            logger.warning(
                "ingestion ownership lost mid-run job=%s company=%s version=%s attempt=%d",
                job_id, company_id, version_id, attempt,
            )
            return  # the new holder owns the job; touch nothing
        except IngestionError as error:
            db.rollback()
            self._handle_failure(db, job_id, company_id, version_id, error, attempt)
            return
        except Exception:  # noqa: BLE001 - classified as retryable-unknown
            logger.exception(
                "ingestion unexpected failure job=%s company=%s version=%s attempt=%d",
                job_id, company_id, version_id, attempt,
            )
            db.rollback()
            self._handle_failure(
                db,
                job_id,
                company_id,
                version_id,
                IngestionError(ERROR_INTERNAL, "Document processing failed.", retryable=True),
                attempt,
            )
            return

        self._queue.complete(db, job_id)
        db.commit()
        logger.info(
            "ingestion succeeded job=%s company=%s version=%s attempt=%d duration_ms=%d",
            job_id, company_id, version_id, attempt,
            int((time.perf_counter() - started) * 1000),
        )

    def _handle_failure(
        self,
        db: Session,
        job_id: str,
        company_id: str,
        version_id: str,
        error: IngestionError,
        attempt: int,
    ) -> None:
        state = self._queue.fail(
            db,
            job_id,
            error=f"{error.code}: {error.user_message}",
            retryable=error.retryable,
            max_attempts=self._max_attempts,
        )
        db.commit()
        if state == JOB_STATE_FAILED:
            mark_version_failed(db, version_id=version_id, company_id=company_id, error=error)
        logger.info(
            "ingestion failure job=%s company=%s version=%s attempt=%d error_code=%s "
            "retryable=%s job_state=%s",
            job_id, company_id, version_id, attempt, error.code, error.retryable, state,
        )


# ----------------------------------------------------------------------------- #
# application-level singleton (started from app startup, flag-gated)
# ----------------------------------------------------------------------------- #

_app_worker: Optional[IngestionWorker] = None
_app_worker_lock = threading.Lock()


def start_application_worker() -> Optional[IngestionWorker]:
    """Start (or return) the process-wide worker. Only called by the startup
    hook when the tenant-corpus flag and the database are both enabled."""
    global _app_worker
    with _app_worker_lock:
        if _app_worker is None:
            from app.db.session import SessionLocal

            _app_worker = IngestionWorker(SessionLocal)
        _app_worker.start()
        return _app_worker


def stop_application_worker() -> None:
    global _app_worker
    with _app_worker_lock:
        if _app_worker is not None:
            _app_worker.stop()
