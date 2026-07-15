"""BlobStore — the seam original document bytes live behind (M1).

Same precedent as `RateLimitStore` (`core/ratelimit.py`): a Protocol with a
single-instance implementation now, a shared implementation later with zero
call-site changes. v1 stores bytes in the `document_blobs` row itself
(PostgreSQL `bytea` / SQLite BLOB); an S3-compatible store replaces only this
module's implementation, never its callers.

Blobs are never served back for download in v1 — they exist for re-ingestion
after parser upgrades and for support. The `put` path is also the designated
future hook for virus scanning (quarantine before the row commits).

Crash-safe write order (binding for every caller — see the M1 migration
docstring in `migrations/versions/f7c3a1b9e2d4_document_ingestion_schema.py`
for the full contract and the orphaned-blob reconciliation strategy):

    version row ('pending')  ->  BlobStore.put  ->  work proceeds

With this DB-backed store both steps share the caller's transaction, so no
intermediate state is ever observable. With object storage the upload happens
before the metadata row commits, so a crash can orphan an object; the periodic
reconciliation sweep (delete blobs unreferenced past a grace window) is what
makes that safe.
"""

from __future__ import annotations

import uuid
from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import DocumentBlob


class BlobStore(Protocol):
    """Storage seam for original document bytes.

    Callers own the transaction: `put` writes the `document_blobs` metadata row
    on the caller's session and never commits, so the crash-safe ordering above
    stays under one transactional roof where the backing store allows it.
    Every read is tenant-scoped — a blob belonging to another tenant is
    indistinguishable from one that does not exist.
    """

    def put(self, db: Session, *, company_id: str, version_id: str, data: bytes) -> DocumentBlob:  # pragma: no cover
        """Store `data` for a document version and return its metadata row."""
        ...

    def get(self, db: Session, *, version_id: str, company_id: str) -> Optional[bytes]:  # pragma: no cover
        """The stored bytes for a version, or None if absent (or another tenant's)."""
        ...

    def delete(self, db: Session, *, version_id: str, company_id: str) -> bool:  # pragma: no cover
        """Remove a version's blob. True if one existed."""
        ...


class DatabaseBlobStore:
    """v1 implementation: bytes live in the `document_blobs.data` column.

    `storage_key` is "db:<blob id>" — self-describing, so rows written by this
    store remain identifiable after a future migration to object storage.
    """

    _KEY_PREFIX = "db:"

    def put(self, db: Session, *, company_id: str, version_id: str, data: bytes) -> DocumentBlob:
        blob_id = str(uuid.uuid4())
        blob = DocumentBlob(
            id=blob_id,
            version_id=version_id,
            company_id=company_id,
            storage_key=f"{self._KEY_PREFIX}{blob_id}",
            byte_size=len(data),
            data=data,
        )
        db.add(blob)
        db.flush()
        return blob

    def _row(self, db: Session, version_id: str, company_id: str) -> Optional[DocumentBlob]:
        return db.execute(
            select(DocumentBlob).where(
                DocumentBlob.version_id == version_id,
                DocumentBlob.company_id == company_id,
            )
        ).scalar_one_or_none()

    def get(self, db: Session, *, version_id: str, company_id: str) -> Optional[bytes]:
        row = self._row(db, version_id, company_id)
        return None if row is None else row.data

    def delete(self, db: Session, *, version_id: str, company_id: str) -> bool:
        row = self._row(db, version_id, company_id)
        if row is None:
            return False
        db.delete(row)
        db.flush()
        return True


def get_blob_store() -> BlobStore:
    """The configured blob store. v1: always the DB-backed implementation."""
    return DatabaseBlobStore()
