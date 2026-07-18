"""The ingestion pipeline: one claimed job -> staged processing -> atomic
persist, driving the document_versions state machine.

Two operations share this module (explicitly discriminated by
``ingestion_jobs.operation``):

* **ingest** (M2): ``pending → extracting → sectioning → ready`` with the
  transitional ordinal identity (`anchor_algo_version="pre-m3-transitional"`).
  `ready` here means **parsed and sectionized** — deliberately NOT
  generation-eligible (the M2→M3 lifecycle contract, DECISIONS.md
  2026-07-16).
* **finalize** (M3): the complete approved path
  ``pending → extracting → sectioning → anchoring → classifying → ready`` on
  a NEW successor version re-ingested from the retained source blob: final
  versioned anchors (+ deterministic inheritance), internal citation
  identities, deterministic module classification, classification
  signatures, and the canonical final manifest. The transitional predecessor
  row and its sections are never touched.

Shared invariants:

* Transitions are validated (`_STATE_TRANSITIONS`); a restart after a stale
  claim legitimately re-enters `extracting` from any in-flight stage. There
  is no `pending → ready` shortcut and `ready` is immutable.
* Derived rows become visible atomically: sections are deleted and rewritten
  inside the same transaction that marks the version `ready`, so a partial
  section/anchor/classification set is never observable and retries never
  duplicate rows.
* `documents.current_version_id` has exactly ONE flip site
  (`_flip_current_version`): a guarded conditional UPDATE that only assigns a
  `ready` version and can never move the pointer to a lower `version_no` —
  a stale finalizer cannot overwrite a newer ready version. A failed version
  leaves the previous working version (and the document's `ready` status)
  untouched.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import Counter
from typing import Callable, List, Optional

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.anchors import (
    ANCHOR_ALGO_VERSION,
    PriorSection,
    assign_anchors,
    prefix_candidates,
    render_citation_id,
)
from app.ingestion.classifier import (
    CLASSIFIER_VERSION,
    SectionClassification,
    classify_section,
    version_signature,
)
from app.ingestion.errors import (
    ERROR_ANCHORING_FAILED,
    ERROR_CITATION_PREFIX_FAILED,
    ERROR_CLASSIFICATION_FAILED,
    ERROR_EMPTY_DOCUMENT,
    ERROR_INTERNAL,
    ERROR_MISSING_BLOB,
    ERROR_MODULE_INVALID,
    ERROR_UNSUPPORTED_TARGET,
    IngestionError,
)
from app.ingestion.finalization_target import build_finalization_target
from app.ingestion.manifest import (
    build_manifest,
    manifest_sha256 as final_manifest_sha256,
    section_manifest_entry,
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
    VERSION_STATUS_ANCHORING,
    VERSION_STATUS_CLASSIFYING,
    VERSION_STATUS_EXTRACTING,
    VERSION_STATUS_FAILED,
    VERSION_STATUS_PENDING,
    VERSION_STATUS_READY,
    VERSION_STATUS_SECTIONING,
)
from app.modules.loader import DomainModule, ModuleValidationError, get_active_module
from app.services.blob_store import BlobStore, get_blob_store

logger = logging.getLogger("evidentia.ingestion")

MARKDOWN_MIME = "text/markdown"
TEXT_MIME = "text/plain"

# The M3 finalization engine target is the COMPLETE target digest
# (`finalization_target.build_finalization_target(...).digest`), never a
# single component version: which parser, normalizer, sectionizer, anchor
# algorithm, inheritance, classifier, module (id/version/digest/signature
# format), manifest version and thresholds/weights a successor was produced
# for. It participates in the one-successor-per-(source, target) uniqueness,
# so changing ANY load-bearing component re-finalizes into a new successor.

_STATE_TRANSITIONS = {
    VERSION_STATUS_PENDING: {VERSION_STATUS_EXTRACTING, VERSION_STATUS_FAILED},
    # <stage> -> extracting: a stale-claim restart re-enters the pipeline.
    VERSION_STATUS_EXTRACTING: {
        VERSION_STATUS_EXTRACTING,
        VERSION_STATUS_SECTIONING,
        VERSION_STATUS_FAILED,
    },
    VERSION_STATUS_SECTIONING: {
        VERSION_STATUS_EXTRACTING,
        VERSION_STATUS_ANCHORING,   # M3 finalize path
        VERSION_STATUS_READY,       # M2 ingest path (transitional)
        VERSION_STATUS_FAILED,
    },
    VERSION_STATUS_ANCHORING: {
        VERSION_STATUS_EXTRACTING,
        VERSION_STATUS_CLASSIFYING,
        VERSION_STATUS_FAILED,
    },
    VERSION_STATUS_CLASSIFYING: {
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


class OwnershipLost(RuntimeError):
    """The worker's job ownership was taken by the stale sweep mid-processing.
    The holder must stop immediately without failing the version — another
    holder owns it now."""


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


def _flip_current_version(db: Session, document: Document, version: DocumentVersion) -> bool:
    """THE controlled flip site (M1 decision: no DB FK; application-enforced;
    only ever assigns a ready version).

    M3 hardening: the flip is a *conditional* UPDATE — it succeeds only while
    the document's current version is NULL or has a strictly lower
    `version_no`, so a stale or lower finalization can never move the pointer
    backwards, on any database, regardless of interleaving. Returns whether
    the pointer moved (a newer ready version keeps it either way).
    """
    if version.status != VERSION_STATUS_READY:  # pragma: no cover - guarded by caller
        raise InvalidTransition(
            f"current_version_id may only flip to a ready version, not {version.status}"
        )
    current_no = (
        select(DocumentVersion.version_no)
        .where(
            DocumentVersion.id == Document.current_version_id,
            DocumentVersion.document_id == document.id,
        )
        .scalar_subquery()
    )
    result = db.execute(
        update(Document)
        .where(
            Document.id == document.id,
            Document.company_id == version.company_id,
            or_(Document.current_version_id.is_(None), current_no < version.version_no),
        )
        .values(current_version_id=version.id, status=DOCUMENT_STATUS_READY)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _load_source_bytes(
    db: Session, blobs: BlobStore, version: DocumentVersion, company_id: str
) -> Optional[bytes]:
    """The version's stored bytes. A finalization successor carries no blob of
    its own — it deliberately reuses the retained source version's blob (same
    physical bytes, no duplication), resolved through `source_version_id`."""
    data = blobs.get(db, version_id=version.id, company_id=company_id)
    if data is None and version.source_version_id:
        data = blobs.get(db, version_id=version.source_version_id, company_id=company_id)
    return data


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

    data = _load_source_bytes(db, blobs, version, company_id)
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
    _flip_current_version(db, document, version)
    db.commit()

    logger.info(
        "ingestion ready company=%s document=%s version=%s version_no=%s format=%s "
        "bytes=%s chars=%s sections=%s duration_ms=%d",
        company_id, document.id, version.id, version.version_no, source_format,
        len(data), len(text), len(drafts), int((time.perf_counter() - started) * 1000),
    )
    return version


# --------------------------------------------------------------------------- #
# M3 finalization: successor processing with final identity + classification
# --------------------------------------------------------------------------- #


def ensure_citation_prefix(db: Session, document: Document) -> str:
    """Mint the document's immutable citation prefix if it does not exist yet.

    Deterministic candidate sequence from the title; the tenant-scoped unique
    index (`uq_documents_company_citation_prefix`) is the allocation
    authority, so two concurrent finalizations can never mint duplicate
    prefixes. Each attempt is a conditional UPDATE inside a SAVEPOINT: the
    loser of a race re-reads and adopts the winner's prefix. Commits the
    allocation so the unique-index lock is never held across long stages.

    Candidate capacity is derived from the configured tenant document quota
    (`evidentia_tenant_max_documents`), so a tenant can always allocate a
    prefix for every document its quota admits — even when every title
    derives the same base (empty/punctuation-only/non-Latin titles all fall
    back to "DOC"). Genuine exhaustion raises a typed, non-retryable error.
    """
    quota = max(1, get_settings().evidentia_tenant_max_documents)
    for candidate in prefix_candidates(document.title, limit=quota):
        db.refresh(document)
        if document.citation_prefix:
            return document.citation_prefix
        try:
            with db.begin_nested():
                result = db.execute(
                    update(Document)
                    .where(Document.id == document.id, Document.citation_prefix.is_(None))
                    .values(citation_prefix=candidate)
                    .execution_options(synchronize_session=False)
                )
        except IntegrityError:
            continue  # candidate taken by another document; try the next
        if result.rowcount == 1:
            db.commit()
            db.refresh(document)
            return document.citation_prefix
        # rowcount 0: a concurrent worker set it first — loop re-reads.
    raise IngestionError(
        ERROR_CITATION_PREFIX_FAILED,
        "A unique citation prefix could not be allocated.",
        retryable=False,
    )


def _load_prior_final_sections(
    db: Session, *, document_id: str, company_id: str, before_version_no: int
) -> List[PriorSection]:
    """The inheritance predecessor: the latest ready version below ours whose
    anchors were minted by a FINAL algorithm. Transitional versions never
    donate anchors — their ordinal ids were never public identity and are
    contractually never reused (DECISIONS.md 2026-07-16)."""
    prior_version = db.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.company_id == company_id,
            DocumentVersion.status == VERSION_STATUS_READY,
            DocumentVersion.version_no < before_version_no,
            DocumentVersion.anchor_algo_version.isnot(None),
            DocumentVersion.anchor_algo_version != ANCHOR_ALGO_TRANSITIONAL,
        )
        .order_by(DocumentVersion.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()
    if prior_version is None:
        return []
    rows = db.execute(
        select(DocumentSection)
        .where(
            DocumentSection.version_id == prior_version.id,
            DocumentSection.company_id == company_id,
        )
        .order_by(DocumentSection.ordinal.asc())
    ).scalars().all()
    return [
        PriorSection(
            anchor_id=row.anchor_id,
            text_sha256=row.text_sha256 or "",
            token_set=tuple(row.token_set or ()),
            ordinal=row.ordinal,
            # The COMPLETE canonical heading identity input: heading-kept
            # inheritance compares full normalized paths, never slugs.
            heading_path=tuple(row.heading_path or ()),
        )
        for row in rows
    ]


def _check_ownership(heartbeat: Optional[Callable[[], bool]]) -> None:
    if heartbeat is not None and not heartbeat():
        raise OwnershipLost("job ownership lost during finalization")


def process_finalization(
    db: Session,
    *,
    version_id: str,
    company_id: str,
    blob_store: Optional[BlobStore] = None,
    heartbeat: Optional[Callable[[], bool]] = None,
) -> DocumentVersion:
    """Run the complete M3 path for one successor version:

        extract → sectionize → anchor (+inherit) → classify → atomic persist

    Idempotent: an already-`ready` successor returns immediately; a re-run
    after an interruption deterministically restarts derived processing and
    rewrites the version's sections atomically. Raises IngestionError (typed,
    classified) on failure; job accounting belongs to the caller. The
    optional ``heartbeat`` callback refreshes job ownership between stages
    and aborts (OwnershipLost) if the stale sweep reclaimed the job.
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
        return version  # already finalized (e.g. duplicate stale job)
    if not version.source_version_id and version.finalization_engine is None:
        raise IngestionError(ERROR_INTERNAL, "Not a finalization version.")

    document = db.execute(
        select(Document)
        .where(Document.id == version.document_id, Document.company_id == company_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if document is None:
        raise IngestionError(ERROR_INTERNAL, "Document not found.")

    # The module must be valid AND engine-compatible before any work: an
    # invalid or incompatible pack fails closed (it cannot even form a target).
    source_format = resolve_source_format(document)
    try:
        module = get_active_module()
        target = build_finalization_target(source_format, module)
    except ModuleValidationError as exc:
        logger.error("classification module invalid: %s", exc)
        raise IngestionError(
            ERROR_MODULE_INVALID,
            "The classification module is unavailable.",
            retryable=False,
        ) from exc

    # Pinned-target verification: the job was enqueued for one COMPLETE
    # target; this process must reproduce exactly that target or refuse.
    # A worker running newer/older code, a different module pack or different
    # thresholds must never silently produce a different artifact.
    if version.finalization_engine != target.digest:
        logger.warning(
            "finalization target unsupported company=%s version=%s pinned=%s current=%s",
            company_id, version.id, version.finalization_engine, target.digest,
        )
        raise IngestionError(
            ERROR_UNSUPPORTED_TARGET,
            "This document version was queued for a different processing engine version.",
            retryable=False,
        )

    parser = get_parser(source_format)

    # -- extract -------------------------------------------------------------- #
    transition_version(version, VERSION_STATUS_EXTRACTING)
    db.commit()  # stage visible to polling
    _check_ownership(heartbeat)

    data = _load_source_bytes(db, blobs, version, company_id)
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
            "finalization parse failed company=%s document=%s version=%s format=%s",
            company_id, document.id, version.id, source_format,
        )
        raise IngestionError("parse_failed", "The document could not be parsed.") from exc

    # -- sectionize ------------------------------------------------------------ #
    transition_version(version, VERSION_STATUS_SECTIONING)
    db.commit()
    _check_ownership(heartbeat)

    drafts = sectionize(doc_ir)
    if not drafts:
        raise IngestionError(ERROR_EMPTY_DOCUMENT, "The document contains no extractable content.")

    # -- anchor ---------------------------------------------------------------- #
    transition_version(version, VERSION_STATUS_ANCHORING)
    db.commit()
    _check_ownership(heartbeat)

    prefix = ensure_citation_prefix(db, document)
    prior_sections = _load_prior_final_sections(
        db,
        document_id=document.id,
        company_id=company_id,
        before_version_no=version.version_no,
    )
    try:
        assignments = assign_anchors(drafts, prior_sections)
    except ValueError as exc:
        logger.error(
            "anchoring failed company=%s document=%s version=%s: %s",
            company_id, document.id, version.id, exc,
        )
        raise IngestionError(
            ERROR_ANCHORING_FAILED,
            "Stable section identities could not be assigned.",
            retryable=False,
        ) from exc

    # -- classify --------------------------------------------------------------- #
    transition_version(version, VERSION_STATUS_CLASSIFYING)
    db.commit()
    _check_ownership(heartbeat)

    try:
        classifications: List[SectionClassification] = [
            classify_section(draft, module, anchor_id=assignment.anchor_id)
            for draft, assignment in zip(drafts, assignments)
        ]
    except Exception as exc:  # noqa: BLE001 - classified as terminal, typed
        logger.exception(
            "classification failed company=%s document=%s version=%s",
            company_id, document.id, version.id,
        )
        raise IngestionError(
            ERROR_CLASSIFICATION_FAILED,
            "Deterministic classification failed.",
            retryable=False,
        ) from exc

    # -- manifest + atomic persist ------------------------------------------------ #
    # The persisted engine_versions IS the complete target projection (plus
    # its digest), so a stored version is self-describing for eligibility.
    engine_versions = target.engine_versions()
    manifest_sections = [
        section_manifest_entry(
            ordinal=draft.ordinal,
            anchor_id=assignment.anchor_id,
            citation_id=render_citation_id(prefix, assignment.anchor_id),
            text_sha256=draft.text_sha256,
            heading_path=draft.heading_path,
            depth=draft.depth,
            char_count=draft.char_count,
            has_tables=draft.has_tables,
            has_omitted_content=draft.has_omitted_content,
            category=cls.category,
            topics=cls.topics,
            market_flags=cls.market_flags,
            injection_flags=cls.injection_flags,
            keywords=cls.keywords,
            persona_affinity=cls.persona_affinity,
            matched_rules=cls.matched_rules,
            classification_signature=cls.signature,
            anchor_provenance=assignment.provenance(),
        )
        for draft, assignment, cls in zip(drafts, assignments, classifications)
    ]
    extracted_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = build_manifest(
        content_sha256=version.content_sha256 or "",
        extracted_sha256=extracted_sha256,
        citation_prefix=prefix,
        engine_versions=engine_versions,
        sections=manifest_sections,
    )

    # One transaction: replace any partial rows from an interrupted attempt,
    # write the full final section set, stamp identity + signatures + manifest,
    # mark ready, and conditionally flip the document pointer.
    db.execute(delete(DocumentSection).where(DocumentSection.version_id == version.id))
    for draft, assignment, cls in zip(drafts, assignments, classifications):
        db.add(
            DocumentSection(
                company_id=company_id,
                document_id=document.id,
                version_id=version.id,
                anchor_id=assignment.anchor_id,
                citation_id=render_citation_id(prefix, assignment.anchor_id),
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
                category=cls.category,
                topics=cls.topics,
                keywords=cls.keywords,
                market_flags=cls.market_flags,
                persona_affinity=cls.persona_affinity,
                injection_flags=cls.injection_flags,
                classifier_version=CLASSIFIER_VERSION,
                signature_pack_version=module.signature_pack_version,
                anchor_provenance=assignment.provenance(),
                matched_rules=cls.matched_rules,
                classification_signature=cls.signature,
            )
        )

    version.extracted_sha256 = extracted_sha256
    version.manifest_sha256 = final_manifest_sha256(manifest)
    version.parser_name = parser.name
    version.parser_version = f"{parser.version}+sectionizer-{SECTIONIZER_VERSION}"
    version.anchor_algo_version = ANCHOR_ALGO_VERSION
    version.engine_versions = engine_versions
    version.classification_signature = version_signature(
        [cls.signature for cls in classifications], module
    )
    version.char_count = len(text)
    version.section_count = len(drafts)
    version.error_code = None
    version.error_detail = None
    transition_version(version, VERSION_STATUS_READY)
    flipped = _flip_current_version(db, document, version)
    db.commit()

    decisions = Counter(a.decision for a in assignments)
    logger.info(
        "finalization ready company=%s document=%s source_version=%s version=%s "
        "version_no=%s sections=%d anchors=%s prefix_set=%s flipped=%s "
        "anchor_algo=%s module=%s classifier=%s duration_ms=%d",
        company_id, document.id, version.source_version_id, version.id,
        version.version_no, len(drafts), dict(sorted(decisions.items())),
        bool(prefix), flipped, ANCHOR_ALGO_VERSION, module.signature_pack_version,
        CLASSIFIER_VERSION, int((time.perf_counter() - started) * 1000),
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
