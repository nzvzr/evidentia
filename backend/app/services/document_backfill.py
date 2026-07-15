"""Backfill: give existing `content_text` documents a real version 1 (M1).

Existing tenant documents were created through the JSON upload path and hold
their content only in the deprecated `documents.content_text` column — they
are inert to the ingestion pipeline. This backfill makes them real: each one
gets a `document_versions` row (version 1), its original bytes in the blob
store, and a queued ingestion job for the M2 worker to sectionize/classify
when it lands. No data is lost and `content_text` is left untouched (its
removal is a separate, later milestone gated on backfill verification).

Idempotent by construction: a document that already has any version row is
skipped, so re-running the command is always safe. Each document commits as
one unit, so an interrupted run leaves only complete documents plus untouched
ones — never a half-migrated row.

Write order per document (the crash-safe contract from the M1 migration
docstring): version row ('pending') -> BlobStore.put -> document metadata +
job enqueue -> commit. With the v1 DB-backed BlobStore all steps share one
transaction, so a crash cannot leave any intermediate state at all.

Versions created here are 'pending', not 'ready': extraction/sectionization
does not exist until M2, and a version must never be visible to generation
before its sections are complete. Consequently `current_version_id` stays
NULL and nothing about today's behavior changes (the flag is off anyway).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import (
    DOCUMENT_STATUS_PROCESSING,
    Document,
    DocumentVersion,
)
from app.services.blob_store import BlobStore, get_blob_store
from app.services.job_queue import JobQueue, get_job_queue

logger = logging.getLogger("evidentia.backfill")

# What a JSON-upload document's text is stored as when synthesized into bytes.
BACKFILL_MIME_TYPE = "text/plain"


@dataclass
class BackfillResult:
    backfilled: List[str] = field(default_factory=list)  # document ids given a version 1
    skipped_has_version: List[str] = field(default_factory=list)
    skipped_no_content: List[str] = field(default_factory=list)

    @property
    def total_examined(self) -> int:
        return len(self.backfilled) + len(self.skipped_has_version) + len(self.skipped_no_content)


def backfill_content_text_documents(
    db: Session,
    *,
    company_id: Optional[str] = None,
    blob_store: Optional[BlobStore] = None,
    job_queue: Optional[JobQueue] = None,
    dry_run: bool = False,
) -> BackfillResult:
    """Synthesize version 1 for every content_text document without versions.

    `company_id` restricts the run to one tenant (useful for staged rollout);
    None means every tenant. Commits per document unless `dry_run`.
    """
    blobs = blob_store or get_blob_store()
    jobs = job_queue or get_job_queue()
    result = BackfillResult()

    query = select(Document).order_by(Document.created_at)
    if company_id:
        query = query.where(Document.company_id == company_id)

    for doc in db.execute(query).scalars().all():
        has_version = (
            db.execute(
                select(DocumentVersion.id).where(DocumentVersion.document_id == doc.id).limit(1)
            ).scalar_one_or_none()
            is not None
        )
        if has_version:
            result.skipped_has_version.append(doc.id)
            continue

        text = doc.content_text or ""
        if not text.strip():
            result.skipped_no_content.append(doc.id)
            continue

        if dry_run:
            result.backfilled.append(doc.id)
            continue

        data = text.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()

        # Crash-safe order: version row (pending) -> blob put -> the rest.
        version = DocumentVersion(
            document_id=doc.id,
            company_id=doc.company_id,
            version_no=1,
            content_sha256=digest,
            char_count=len(text),
            created_by=None,
        )
        db.add(version)
        db.flush()

        blobs.put(db, company_id=doc.company_id, version_id=version.id, data=data)

        doc.content_sha256 = digest
        doc.size_bytes = len(data)
        if not doc.mime_type:
            doc.mime_type = BACKFILL_MIME_TYPE
        # 'processing' = a version exists but is not ready; the M2 worker takes
        # it from here. current_version_id stays NULL until a version is ready.
        doc.status = DOCUMENT_STATUS_PROCESSING

        jobs.enqueue(db, company_id=doc.company_id, document_id=doc.id, version_id=version.id)

        # One document = one commit: an interrupted run leaves only complete
        # units, and the idempotency check above makes re-running safe.
        db.commit()
        result.backfilled.append(doc.id)
        logger.info("backfilled document %s (company %s)", doc.id, doc.company_id)

    return result
