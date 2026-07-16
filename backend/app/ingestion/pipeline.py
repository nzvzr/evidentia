"""The M2 ingestion pipeline: one claimed job -> extract -> sectionize ->
atomic persist, driving the document_versions state machine.

State machine (M2 subset of the states reserved in M1):

    pending ──▶ extracting ──▶ sectioning ──▶ ready
       │             │              │
       └─────────────┴──────────────┴───────▶ failed

* Transitions are validated (`_STATE_TRANSITIONS`); a restart after a stale
  claim legitimately re-enters `extracting` from `extracting`/`sectioning`.
* `ready` in M2 means **parsed and sectionized** — deliberately NOT "used by
  report generation": classification/anchors land in M3 and generation reads
  tenant sections only from M4. `anchor_algo_version` is stamped
  ``pre-m3-transitional`` to make that machine-readable.
* A version's derived rows become visible atomically: sections are deleted and
  rewritten inside the same transaction that marks the version `ready`, so a
  partial section set is never observable and retries never duplicate rows.
* `documents.current_version_id` has exactly ONE flip site
  (`_flip_current_version`), which only ever assigns a `ready` version — the
  M1 decision. A failed new version leaves the previous working version (and
  the document's `ready` status) untouched.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.errors import (
    ERROR_EMPTY_DOCUMENT,
    ERROR_INTERNAL,
    ERROR_MISSING_BLOB,
    IngestionError,
)
from app.ingestion.normalize import decode_and_normalize
from app.ingestion.parsers import (
    FORMAT_MARKDOWN,
    FORMAT_TEXT,
    get_parser,
)
from app.ingestion.sectionizer import (
    ANCHOR_ALGO_TRANSITIONAL,
    SECTIONIZER_VERSION,
    manifest_sha256,
    sectionize,
)
from app.models.db_models import (
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_READY,
    Document,
    DocumentSection,
    DocumentVersion,
    IngestionJob,
    VERSION_STATUS_EXTRACTING,
    VERSION_STATUS_FAILED,
    VERSION_STATUS_PENDING,
    VERSION_STATUS_READY,
    VERSION_STATUS_SECTIONING,
)
from app.services.blob_store import BlobStore, get_blob_store

logger = logging.getLogger("evidentia.ingestion")

MARKDOWN_MIME = "text/markdown"
TEXT_MIME = "text/plain"

_STATE_TRANSITIONS = {
    VERSION_STATUS_PENDING: {VERSION_STATUS_EXTRACTING, VERSION_STATUS_FAILED},
    # extracting -> extracting: a stale-claim restart re-enters the stage.
    VERSION_STATUS_EXTRACTING: {
        VERSION_STATUS_EXTRACTING,
        VERSION_STATUS_SECTIONING,
        VERSION_STATUS_FAILED,
    },
    VERSION_STATUS_SECTIONING: {
        VERSION_STATUS_EXTRACTING,
        VERSION_STATUS_READY,
        VERSION_STATUS_FAILED,
    },
    # failed -> pending is the explicit retry reset (API-controlled).
    VERSION_STATUS_FAILED: {VERSION_STATUS_PENDING},
    VERSION_STATUS_READY: set(),  # immutable once ready
}


class InvalidTransition(RuntimeError):
    pass


def transition_version(version: DocumentVersion, to_state: str) -> None:
    """The single validated write point for version status."""
    allowed = _STATE_TRANSITIONS.get(version.status, set())
    if to_state not in allowed:
        raise InvalidTransition(f"version {version.id}: {version.status} -> {to_state}")
    version.status = to_state


def resolve_source_format(document: Document) -> str:
    """Declared Markdown/plain-text source for this document.

    Upload documents carry an authoritative mime_type. Backfilled JSON-upload
    documents declared their kind in `type` ("MD"/"TXT") and often a filename
    in metadata; those signals are honored in a fixed order so the same row
    always resolves the same way.
    """
    mime = (document.mime_type or "").lower()
    if mime == MARKDOWN_MIME:
        return FORMAT_MARKDOWN

    filename = (document.original_filename or "").lower()
    if not filename and isinstance(document.metadata_json, dict):
        filename = str(document.metadata_json.get("filename", "")).lower()
    if filename.endswith(".md"):
        return FORMAT_MARKDOWN

    doc_type = (document.type or "").strip().lower()
    if doc_type in ("md", "markdown"):
        return FORMAT_MARKDOWN
    return FORMAT_TEXT


def _flip_current_version(document: Document, version: DocumentVersion) -> None:
    """THE controlled flip site (M1 decision: no DB FK; application-enforced;
    only ever assigns a ready version)."""
    if version.status != VERSION_STATUS_READY:  # pragma: no cover - guarded by caller
        raise InvalidTransition(
            f"current_version_id may only flip to a ready version, not {version.status}"
        )
    document.current_version_id = version.id
    document.status = DOCUMENT_STATUS_READY


def process_version(
    db: Session,
    *,
    version_id: str,
    company_id: str,
    blob_store: Optional[BlobStore] = None,
) -> DocumentVersion:
    """Run extraction + sectionization for one version. Raises IngestionError
    (typed, classified) on failure; the caller (worker or test harness) owns
    job accounting and failure persistence via `mark_version_failed`.

    Idempotent: an already-`ready` version returns immediately; a re-run after
    an interruption rewrites the version's sections atomically.
    """
    settings = get_settings()
    blobs = blob_store or get_blob_store()
    started = time.perf_counter()

    version = db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.id == version_id, DocumentVersion.company_id == company_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if version is None:
        raise IngestionError(ERROR_INTERNAL, "Document version not found.")
    if version.status == VERSION_STATUS_READY:
        return version  # already done (e.g. duplicate stale job)

    document = db.execute(
        select(Document)
        .where(Document.id == version.document_id, Document.company_id == company_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if document is None:
        raise IngestionError(ERROR_INTERNAL, "Document not found.")

    source_format = resolve_source_format(document)
    parser = get_parser(source_format)

    # -- extract ------------------------------------------------------------ #
    transition_version(version, VERSION_STATUS_EXTRACTING)
    db.commit()  # stage visible to polling

    data = blobs.get(db, version_id=version.id, company_id=company_id)
    if data is None:
        raise IngestionError(ERROR_MISSING_BLOB, "The stored document bytes are missing.")

    text = decode_and_normalize(data, max_chars=settings.evidentia_max_extracted_chars)
    if not text.strip():
        raise IngestionError(ERROR_EMPTY_DOCUMENT, "The document contains no text.")

    try:
        doc_ir = parser.parse(text)
    except IngestionError:
        raise
    except Exception as exc:
        logger.exception(
            "ingestion parse failed company=%s document=%s version=%s format=%s",
            company_id, document.id, version.id, source_format,
        )
        raise IngestionError(
            "parse_failed", "The document could not be parsed.",
        ) from exc

    # -- sectionize ---------------------------------------------------------- #
    transition_version(version, VERSION_STATUS_SECTIONING)
    db.commit()

    drafts = sectionize(doc_ir)
    if not drafts:
        raise IngestionError(ERROR_EMPTY_DOCUMENT, "The document contains no extractable content.")

    # -- persist atomically --------------------------------------------------- #
    # One transaction: replace any partial rows from an interrupted attempt,
    # write the full section set, mark ready, flip the document pointer.
    db.execute(delete(DocumentSection).where(DocumentSection.version_id == version.id))
    for draft in drafts:
        db.add(
            DocumentSection(
                company_id=company_id,
                document_id=document.id,
                version_id=version.id,
                anchor_id=draft.anchor_id,
                citation_id=draft.citation_id,
                ordinal=draft.ordinal,
                depth=draft.depth,
                heading_path=draft.heading_path,
                title=draft.title[:500],
                text=draft.text,
                excerpt=draft.excerpt,
                text_sha256=draft.text_sha256,
                char_count=draft.char_count,
                has_tables=draft.has_tables,
                has_omitted_content=draft.has_omitted_content,
                token_set=draft.token_set,
            )
        )

    version.extracted_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    version.manifest_sha256 = manifest_sha256(drafts)
    version.parser_name = parser.name
    version.parser_version = f"{parser.version}+sectionizer-{SECTIONIZER_VERSION}"
    version.anchor_algo_version = ANCHOR_ALGO_TRANSITIONAL
    version.char_count = len(text)
    version.section_count = len(drafts)
    version.error_code = None
    version.error_detail = None
    transition_version(version, VERSION_STATUS_READY)
    _flip_current_version(document, version)
    db.commit()

    logger.info(
        "ingestion ready company=%s document=%s version=%s version_no=%s format=%s "
        "bytes=%s chars=%s sections=%s duration_ms=%d",
        company_id, document.id, version.id, version.version_no, source_format,
        len(data), len(text), len(drafts), int((time.perf_counter() - started) * 1000),
    )
    return version


def mark_version_failed(
    db: Session, *, version_id: str, company_id: str, error: IngestionError
) -> None:
    """Persist a typed failure on the version without ever degrading a
    previously working document: the document only reports `failed` when no
    ready current version exists."""
    version = db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.id == version_id, DocumentVersion.company_id == company_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if version is None or version.status == VERSION_STATUS_READY:
        return
    if version.status != VERSION_STATUS_FAILED:
        transition_version(version, VERSION_STATUS_FAILED)
    version.error_code = error.code
    version.error_detail = error.user_message

    document = db.execute(
        select(Document)
        .where(Document.id == version.document_id, Document.company_id == company_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if document is not None and document.current_version_id is None:
        document.status = DOCUMENT_STATUS_FAILED
    db.commit()

    logger.info(
        "ingestion failed company=%s document=%s version=%s error_code=%s retryable=%s",
        company_id, version.document_id, version.id, error.code, error.retryable,
    )
