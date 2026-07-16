"""Upload validation + document/version creation for the M2 multipart path.

Everything security-relevant about accepting a customer file lives here so
the API layer stays a thin translation to HTTP:

* strict allowlist (.md/.txt) with content sniffing - the extension is only a
  consistency signal, the bytes decide (binary magic / NUL / non-UTF-8 is
  rejected regardless of extension, and a declared non-text part content-type
  contradicting the extension is rejected as a mismatch);
* bounded streaming reads - the per-file byte cap is enforced while reading
  and SHA-256 is computed from the actual bytes, never from headers;
* filename sanitization - path components, control characters and leading
  dots are stripped; the result is a *display* name only (blob storage is
  content-addressed behind the BlobStore seam; no filesystem path is ever
  derived from user input);
* tenant quotas under the company row lock - the count/size check and the
  insert are one critical section, so concurrent uploads cannot race past
  the quota (same locking idiom as the membership owner invariant);
* duplicate/version semantics (DOCUMENT_INGESTION_ARCHITECTURE.md section 11):
  byte-identical new-document upload returns the existing document
  explicitly; byte-identical new *version* is an explicit no-op; a failed
  version never blocks retrying with the same or fixed bytes;
* crash-safe write order (binding M1 contract): version row (`pending`) ->
  BlobStore.put -> document metadata + job enqueue -> single commit.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.normalize import decode_bytes, normalize_text
from app.ingestion.errors import IngestionError
from app.ingestion.parsers import FORMAT_MARKDOWN, FORMAT_TEXT
from app.ingestion.pipeline import MARKDOWN_MIME, TEXT_MIME
from app.models.db_models import (
    DOCUMENT_STATUS_PROCESSING,
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    VERSION_STATUS_FAILED,
    VERSION_STATUS_PENDING,
    Company,
    Document,
    DocumentBlob,
    DocumentVersion,
    IngestionJob,
)
from app.repositories import documents as documents_repo
from app.services.blob_store import BlobStore, get_blob_store
from app.services.job_queue import JobQueue, get_job_queue

logger = logging.getLogger("evidentia.ingestion.upload")

# Stable, user-safe rejection codes (the API maps them to status codes).
CODE_FLAG_DISABLED = "tenant_corpus_disabled"
CODE_MISSING_FILE = "missing_file"
CODE_TOO_MANY_FILES = "too_many_files"
CODE_UNSUPPORTED_EXTENSION = "unsupported_extension"
CODE_UNSUPPORTED_TYPE = "unsupported_type"
CODE_TYPE_MISMATCH = "type_mismatch"
CODE_FILE_TOO_LARGE = "file_too_large"
CODE_EMPTY_FILE = "empty_file"
CODE_INVALID_ENCODING = "invalid_encoding"
CODE_EXTRACTION_TOO_LARGE = "extraction_too_large"
CODE_DOCUMENT_QUOTA = "document_quota_exceeded"
CODE_STORAGE_QUOTA = "storage_quota_exceeded"
CODE_VERSION_NOT_FAILED = "version_not_failed"


class UploadRejected(Exception):
    """A typed, user-safe rejection. Never carries file content, storage
    internals or a traceback."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


_ALLOWED_EXTENSIONS = {".md": FORMAT_MARKDOWN, ".txt": FORMAT_TEXT}

# Declared part content-types that are consistent with a text upload. Anything
# else declared alongside a .md/.txt extension is a mismatch.
_ACCEPTABLE_DECLARED_TYPES_PREFIX = ("text/",)
_ACCEPTABLE_DECLARED_TYPES = {"", "application/octet-stream", "application/markdown"}

# Binary signatures that must never pass the text sniff regardless of how they
# decode (defense in depth beside the NUL/UTF-8 checks).
_BINARY_MAGIC = (
    b"%PDF",          # PDF
    b"PK\x03\x04",    # zip / docx / xlsx
    b"\x7fELF",       # ELF
    b"MZ",            # PE
    b"\x89PNG",       # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF8",          # GIF
    b"\xd0\xcf\x11\xe0",  # OLE (legacy office)
)

_CONTROL_IN_NAME = re.compile(r"[\x00-\x1f\x7f]")
_MAX_FILENAME_CHARS = 200

_FORMAT_MIME = {FORMAT_MARKDOWN: MARKDOWN_MIME, FORMAT_TEXT: TEXT_MIME}
_FORMAT_TYPE = {FORMAT_MARKDOWN: "MD", FORMAT_TEXT: "TXT"}

_CHUNK = 64 * 1024


def sanitize_filename(raw: Optional[str]) -> str:
    """A safe *display* filename: last path segment, control chars stripped,
    no leading dots, bounded length. Never used to build a storage path."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL_IN_NAME.sub("", name).strip().lstrip(".")
    name = name[:_MAX_FILENAME_CHARS].strip()
    return name or "document.txt"


def detect_format(filename: str, declared_content_type: Optional[str], head: bytes) -> str:
    """Strict allowlist + content sniffing. The extension is a consistency
    signal only; the bytes decide."""
    dot = filename.rfind(".")
    extension = filename[dot:].lower() if dot >= 0 else ""
    file_format = _ALLOWED_EXTENSIONS.get(extension)
    if file_format is None:
        raise UploadRejected(
            415,
            CODE_UNSUPPORTED_EXTENSION,
            "Only .md (Markdown) and .txt (plain text) files are supported.",
        )

    declared = (declared_content_type or "").split(";")[0].strip().lower()
    if declared not in _ACCEPTABLE_DECLARED_TYPES and not declared.startswith(
        _ACCEPTABLE_DECLARED_TYPES_PREFIX
    ):
        raise UploadRejected(
            415,
            CODE_TYPE_MISMATCH,
            f"The declared content type does not match a {extension} text document.",
        )

    for magic in _BINARY_MAGIC:
        if head.startswith(magic):
            raise UploadRejected(
                415,
                CODE_UNSUPPORTED_TYPE,
                "The file content is not text. Only Markdown and plain-text documents are supported.",
            )
    return file_format


async def read_bounded(upload, max_bytes: int) -> Tuple[bytes, str]:
    """Read an UploadFile in bounded chunks, hashing as we go. Rejects the
    moment the cap is crossed - the declared size is never trusted."""
    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadRejected(
                413,
                CODE_FILE_TOO_LARGE,
                f"The file exceeds the {max_bytes:,}-byte upload limit.",
            )
        hasher.update(chunk)
        chunks.append(chunk)
    return b"".join(chunks), hasher.hexdigest()


def validate_text_payload(data: bytes) -> str:
    """Sniff + decode + normalize-check the payload. Returns the decoded text
    (used only for validation here; the worker re-derives it from the blob)."""
    if not data:
        raise UploadRejected(400, CODE_EMPTY_FILE, "The file is empty.")
    settings = get_settings()
    try:
        text = decode_bytes(data)
        text = normalize_text(text, max_chars=settings.evidentia_max_extracted_chars)
    except IngestionError as exc:
        if exc.code == CODE_EXTRACTION_TOO_LARGE:
            raise UploadRejected(413, CODE_EXTRACTION_TOO_LARGE, exc.user_message) from None
        raise UploadRejected(400, CODE_INVALID_ENCODING, exc.user_message) from None
    if not text.strip():
        raise UploadRejected(400, CODE_EMPTY_FILE, "The file contains no text.")
    return text


# --------------------------------------------------------------------------- #
# quotas (checked under the company row lock - no check-then-write race)
# --------------------------------------------------------------------------- #


def _lock_company(db: Session, company_id: str) -> None:
    """Serialize per-tenant quota decisions. Same idiom as the membership
    owner-invariant lock: real `FOR UPDATE` on PostgreSQL, a no-op UPDATE
    (write-lock promotion) on SQLite."""
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "sqlite":
        db.execute(
            update(Company)
            .where(Company.id == company_id)
            .values(updated_at=Company.updated_at)
            .execution_options(synchronize_session=False)
        )
        return
    db.execute(select(Company).where(Company.id == company_id).with_for_update()).scalar_one_or_none()


def _enforce_quotas_locked(db: Session, company_id: str, new_bytes: int, *, new_document: bool) -> None:
    settings = get_settings()
    if new_document:
        doc_count = db.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.company_id == company_id, Document.deleted_at.is_(None))
        ).scalar_one()
        if doc_count >= settings.evidentia_tenant_max_documents:
            raise UploadRejected(
                403,
                CODE_DOCUMENT_QUOTA,
                "Your organization has reached its document limit.",
            )

    # Stored bytes are accounted from blob sizes (authoritative for storage).
    stored = db.execute(
        select(func.coalesce(func.sum(DocumentBlob.byte_size), 0)).where(
            DocumentBlob.company_id == company_id
        )
    ).scalar_one()
    if stored + new_bytes > settings.evidentia_tenant_max_total_bytes:
        raise UploadRejected(
            403,
            CODE_STORAGE_QUOTA,
            "Your organization has reached its document storage limit.",
        )


# --------------------------------------------------------------------------- #
# creation / dedupe / versions / retry
# --------------------------------------------------------------------------- #


@dataclass
class UploadOutcome:
    document: Document
    version: DocumentVersion
    created: bool  # False => duplicate/no-op (nothing new was stored)
    duplicate: bool = False
    noop: bool = False
    retried: bool = False


def latest_version(db: Session, document_id: str, company_id: str) -> Optional[DocumentVersion]:
    return db.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.company_id == company_id,
        )
        .order_by(DocumentVersion.version_no.desc())
        .limit(1)
    ).scalars().first()


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


def _title_from_filename(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return (stem.strip() or "Document")[:300]


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "document"


def create_document_upload(
    db: Session,
    *,
    company_id: str,
    user_id: Optional[str],
    filename: str,
    file_format: str,
    data: bytes,
    digest: str,
    blob_store: Optional[BlobStore] = None,
    job_queue: Optional[JobQueue] = None,
) -> UploadOutcome:
    """New-document upload. Tenant-scoped dedupe on the actual bytes: an
    identical document already in the library is returned explicitly instead
    of storing a duplicate blob/version/job."""
    blobs = blob_store or get_blob_store()
    jobs = job_queue or get_job_queue()

    _lock_company(db, company_id)

    existing = db.execute(
        select(Document)
        .where(
            Document.company_id == company_id,
            Document.content_sha256 == digest,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.asc())
    ).scalars().first()
    if existing is not None:
        version = latest_version(db, existing.id, company_id)
        if version is not None:
            db.commit()  # release the lock; nothing was written
            return UploadOutcome(
                document=existing, version=version, created=False, duplicate=True
            )

    _enforce_quotas_locked(db, company_id, len(data), new_document=True)

    document = Document(
        company_id=company_id,
        title=_title_from_filename(filename),
        slug=_slugify(_title_from_filename(filename)),
        type=_FORMAT_TYPE[file_format],
        category="Uploaded",
        source_type="upload",
        original_filename=filename,
        mime_type=_FORMAT_MIME[file_format],
        content_sha256=digest,
        size_bytes=len(data),
        status=DOCUMENT_STATUS_PROCESSING,
        created_by=user_id,
    )
    db.add(document)
    db.flush()

    version = create_version_with_blob(
        db, document=document, version_no=1, data=data, digest=digest, user_id=user_id,
        blobs=blobs, jobs=jobs,
    )
    db.commit()
    logger.info(
        "upload accepted company=%s user=%s document=%s version=%s format=%s bytes=%d",
        company_id, user_id, document.id, version.id, file_format, len(data),
    )
    return UploadOutcome(document=document, version=version, created=True)


def create_json_document(
    db: Session,
    *,
    company_id: str,
    user_id: Optional[str],
    title: str,
    slug: str,
    doc_type: Optional[str],
    category: Optional[str],
    content_text: Optional[str],
    metadata_json: Optional[dict] = None,
    blob_store: Optional[BlobStore] = None,
    job_queue: Optional[JobQueue] = None,
) -> Tuple[Document, Optional[DocumentVersion]]:
    """Flag-on JSON create, under the SAME abuse bounds as a multipart upload.

    The JSON path routes through the ingestion spine (version 1 + blob +
    queued job — the backfill shape), so it must pay the same costs: the
    company row lock is taken first, then the document-count and stored-byte
    quotas are checked against the actual UTF-8 byte size, and only then are
    the document/version/blob/job rows written. Everything happens in one
    transaction, so a quota rejection leaves no row of any kind behind.

    The flag-off JSON path never reaches this function — it keeps the pre-M2
    behavior byte-for-byte (no lock, no quotas, no ingestion rows).
    """
    blobs = blob_store or get_blob_store()
    jobs = job_queue or get_job_queue()

    data = content_text.encode("utf-8") if (content_text or "").strip() else b""

    _lock_company(db, company_id)
    _enforce_quotas_locked(db, company_id, len(data), new_document=True)

    document = documents_repo.create_document(
        db,
        company_id=company_id,
        title=title,
        slug=slug,
        doc_type=doc_type,
        category=category,
        content_text=content_text,
        metadata_json=metadata_json,
    )

    version: Optional[DocumentVersion] = None
    if data:
        digest = hashlib.sha256(data).hexdigest()
        document.content_sha256 = digest
        document.size_bytes = len(data)
        if not document.mime_type:
            document.mime_type = (
                MARKDOWN_MIME
                if (doc_type or "").strip().lower() in ("md", "markdown")
                else TEXT_MIME
            )
        document.status = DOCUMENT_STATUS_PROCESSING
        version = create_version_with_blob(
            db, document=document, version_no=1, data=data, digest=digest,
            user_id=user_id, blobs=blobs, jobs=jobs,
        )
    db.commit()
    db.refresh(document)
    logger.info(
        "json create accepted company=%s user=%s document=%s version=%s bytes=%d",
        company_id, user_id, document.id, version.id if version else None, len(data),
    )
    return document, version


def create_new_version_upload(
    db: Session,
    *,
    document: Document,
    user_id: Optional[str],
    filename: str,
    file_format: str,
    data: bytes,
    digest: str,
    blob_store: Optional[BlobStore] = None,
    job_queue: Optional[JobQueue] = None,
) -> UploadOutcome:
    """Explicitly-targeted new version. Byte-identical to the latest version =
    no-op (or a retry when that version previously failed); otherwise version
    N+1 with the old versions kept immutable."""
    blobs = blob_store or get_blob_store()
    jobs = job_queue or get_job_queue()
    company_id = document.company_id

    _lock_company(db, company_id)

    latest = latest_version(db, document.id, company_id)
    if latest is not None and latest.content_sha256 == digest:
        if latest.status == VERSION_STATUS_FAILED and not _has_live_job(db, latest.id):
            # Same bytes, previously failed: this is a retry, not a duplicate.
            latest.status = VERSION_STATUS_PENDING
            latest.error_code = None
            latest.error_detail = None
            if document.current_version_id is None:
                document.status = DOCUMENT_STATUS_PROCESSING
            jobs.enqueue(db, company_id=company_id, document_id=document.id, version_id=latest.id)
            db.commit()
            return UploadOutcome(
                document=document, version=latest, created=True, retried=True
            )
        db.commit()  # release the lock; nothing was written
        return UploadOutcome(document=document, version=latest, created=False, noop=True)

    _enforce_quotas_locked(db, company_id, len(data), new_document=False)

    next_no = (latest.version_no if latest is not None else 0) + 1
    version = create_version_with_blob(
        db, document=document, version_no=next_no, data=data, digest=digest,
        user_id=user_id, blobs=blobs, jobs=jobs,
    )
    document.original_filename = filename
    document.mime_type = _FORMAT_MIME[file_format]
    document.type = _FORMAT_TYPE[file_format]
    document.content_sha256 = digest
    document.size_bytes = len(data)
    if document.current_version_id is None:
        document.status = DOCUMENT_STATUS_PROCESSING
    db.commit()
    logger.info(
        "new version accepted company=%s user=%s document=%s version=%s version_no=%d bytes=%d",
        company_id, user_id, document.id, version.id, next_no, len(data),
    )
    return UploadOutcome(document=document, version=version, created=True)


def retry_failed_version(
    db: Session,
    *,
    document: Document,
    job_queue: Optional[JobQueue] = None,
) -> DocumentVersion:
    """Re-enqueue the latest version when (and only when) it failed. Reuses
    the immutable stored bytes; at most one live job (DB-enforced); sections
    are rewritten atomically by the pipeline so retries cannot duplicate them."""
    jobs = job_queue or get_job_queue()
    latest = latest_version(db, document.id, document.company_id)
    if latest is None or latest.status != VERSION_STATUS_FAILED:
        raise UploadRejected(
            409,
            CODE_VERSION_NOT_FAILED,
            "Only a failed document version can be retried.",
        )
    latest.status = VERSION_STATUS_PENDING
    latest.error_code = None
    latest.error_detail = None
    if document.current_version_id is None:
        document.status = DOCUMENT_STATUS_PROCESSING
    jobs.enqueue(
        db, company_id=document.company_id, document_id=document.id, version_id=latest.id
    )
    db.commit()
    logger.info(
        "retry enqueued company=%s document=%s version=%s",
        document.company_id, document.id, latest.id,
    )
    return latest


def create_version_with_blob(
    db: Session,
    *,
    document: Document,
    version_no: int,
    data: bytes,
    digest: str,
    user_id: Optional[str],
    blobs: BlobStore,
    jobs: JobQueue,
) -> DocumentVersion:
    """Binding crash-safe write order: version row (pending) -> blob put ->
    job enqueue. All in the caller's transaction with the DB-backed store."""
    version = DocumentVersion(
        document_id=document.id,
        company_id=document.company_id,
        version_no=version_no,
        content_sha256=digest,
        status=VERSION_STATUS_PENDING,
        created_by=user_id,
    )
    db.add(version)
    db.flush()
    blobs.put(db, company_id=document.company_id, version_id=version.id, data=data)
    jobs.enqueue(
        db, company_id=document.company_id, document_id=document.id, version_id=version.id
    )
    return version
