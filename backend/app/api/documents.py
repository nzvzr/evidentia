"""Document endpoints. Tenant-scoped; the built-in corpus is read-only reference.

The demo corpus is still served as a *fallback* when the tenant has uploaded no
documents of its own, but it is shared reference material with no tenant rows
behind it — it is never writable and never mixes with another tenant's data.

M2 additions (all gated on EVIDENTIA_TENANT_CORPUS_ENABLED; the flag-off
response shapes are byte-for-byte the pre-M2 ones):

* ``POST /api/documents/upload``            — authenticated multipart MD/TXT upload (202)
* ``POST /api/documents/{id}/versions``     — explicit new version for an existing document
* ``POST /api/documents/{id}/retry``        — re-enqueue a failed version
* additive ``ingestion`` object on serialized tenant documents and a
  ``tenantCorpus`` config object on the list response (safe metadata only:
  never blob keys, storage paths, extracted text, tracebacks or queue
  lease internals).

Report generation is untouched: it still reads only the bundled demo corpus
until M4, so tenant sections can never leak into a report from here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.agents.document_reader import list_documents as demo_documents
from app.api.deps import CompanyContext, get_company_context, require_admin
from app.api.limits import enforce_upload
from app.core.config import get_settings
from app.db.session import get_db
from app.models.db_models import Document, DocumentVersion
from app.models.schemas import DocumentCreate
from app.repositories import documents as documents_repo
from app.services import document_upload as upload_service
from app.services.document_upload import UploadOutcome, UploadRejected

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "document"


def _corpus_enabled() -> bool:
    return get_settings().evidentia_tenant_corpus_enabled


def _format_label(doc: Document) -> Optional[str]:
    if doc.mime_type == upload_service.MARKDOWN_MIME:
        return "markdown"
    if doc.mime_type == upload_service.TEXT_MIME:
        return "text"
    return None


def _ingestion_payload(doc: Document, version: Optional[DocumentVersion]) -> Dict[str, Any]:
    """Safe, tenant-visible ingestion state. `ready` here means "parsed and
    sectionized" (pre-M3): honest wording belongs to the UI, the machine-
    readable stage is exact. Never exposes storage keys, section text,
    citation ids (M3 mints those) or queue lease details."""
    payload: Dict[str, Any] = {
        "status": doc.status,
        "stage": version.status if version is not None else None,
        "versionNo": version.version_no if version is not None else None,
        "filename": doc.original_filename,
        "detectedFormat": _format_label(doc),
        "byteSize": doc.size_bytes,
        "sectionCount": version.section_count if version is not None else None,
        "errorCode": version.error_code if version is not None else None,
        "errorMessage": version.error_detail if version is not None else None,
        "updatedAt": doc.updated_at.isoformat() if doc.updated_at else None,
        "sourceType": doc.source_type,
    }
    return payload


def _serialize(doc: Document, version: Optional[DocumentVersion] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": doc.id,
        "companyId": doc.company_id,
        "title": doc.title,
        "slug": doc.slug,
        "type": doc.type,
        "category": doc.category,
        "metadata": doc.metadata_json,
        "createdAt": doc.created_at.isoformat() if doc.created_at else None,
    }
    # Additive, flag-gated: with the corpus off the response shape stays
    # byte-for-byte the pre-M2 one (pinned by test).
    if _corpus_enabled():
        data["ingestion"] = _ingestion_payload(doc, version)
    return data


def _latest_versions(db: Session, company_id: str, document_ids: List[str]) -> Dict[str, DocumentVersion]:
    if not document_ids:
        return {}
    rows = db.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.company_id == company_id,
            DocumentVersion.document_id.in_(document_ids),
        )
        .order_by(DocumentVersion.version_no.asc())
    ).scalars().all()
    latest: Dict[str, DocumentVersion] = {}
    for row in rows:
        latest[row.document_id] = row  # ascending order => last write wins
    return latest


def _upload_config() -> Dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": True,
        "acceptedExtensions": [".md", ".txt"],
        "maxFileBytes": settings.evidentia_upload_max_file_bytes,
    }


@router.get("")
def get_documents(
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    corpus_on = _corpus_enabled()
    if get_settings().is_db_enabled():
        rows = documents_repo.list_documents(db, ctx.company_id)
        if rows:
            latest = (
                _latest_versions(db, ctx.company_id, [r.id for r in rows]) if corpus_on else {}
            )
            body: Dict[str, Any] = {
                "documents": [_serialize(r, latest.get(r.id)) for r in rows]
            }
            if corpus_on:
                body["tenantCorpus"] = _upload_config()
            return body
    # Fallback: the built-in demo corpus metadata (shared read-only reference).
    body = {"documents": demo_documents()}
    if corpus_on:
        body["tenantCorpus"] = _upload_config()
    return body


@router.get("/{document_id}")
def get_document(
    document_id: str,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    doc = documents_repo.get_document(db, document_id, ctx.company_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = None
    if _corpus_enabled():
        version = upload_service.latest_version(db, doc.id, ctx.company_id)
    return _serialize(doc, version)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_document(
    body: DocumentCreate,
    request: Request,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if not _corpus_enabled():
        # Flag off: the pre-M2 behavior byte-for-byte (shape pinned by test).
        # No upload rate limits or quotas existed on this path before M2, so
        # none are introduced here.
        doc = documents_repo.create_document(
            db,
            company_id=ctx.company_id,  # from the session, not the request body
            title=body.title,
            slug=body.slug or _slugify(body.title),
            doc_type=body.type,
            category=body.category,
            content_text=body.contentText,
            metadata_json=body.metadata,
        )
        db.commit()
        db.refresh(doc)
        return _serialize(doc)

    # Approved architecture: with the corpus on, the JSON create path is
    # routed through the same ingestion spine as a pre-extracted MD/TXT
    # source (version 1 + blob + queued job — the backfill shape), so it
    # shares the multipart path's abuse bounds: the upload rate budgets
    # (counted before any row is touched), the company row lock, and the
    # document-count + stored-byte quotas on the actual UTF-8 bytes.
    enforce_upload(request, user_id=ctx.user_id, company_id=ctx.company_id)
    try:
        doc, version = upload_service.create_json_document(
            db,
            company_id=ctx.company_id,  # from the session, not the request body
            user_id=ctx.user_id,
            title=body.title,
            slug=body.slug or _slugify(body.title),
            doc_type=body.type,
            category=body.category,
            content_text=body.contentText,
            metadata_json=body.metadata,
        )
    except UploadRejected as exc:
        db.rollback()  # a rejected create leaves no document/version/blob/job
        raise _reject(exc) from None
    return _serialize(doc, version)


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Dict[str, bool]:
    if not documents_repo.delete_document(db, document_id, ctx.company_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# M2: multipart upload / new version / retry
# --------------------------------------------------------------------------- #


def _reject(exc: UploadRejected) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _require_corpus_enabled() -> None:
    if not _corpus_enabled():
        # Explicit, stable disabled response — never a silent 404.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": upload_service.CODE_FLAG_DISABLED,
                "message": "Document upload is not enabled for this deployment.",
            },
        )


async def _read_single_upload(request: Request) -> tuple[str, str, bytes, str]:
    """Parse the multipart form, enforce the single-file rule and every
    content bound, and return (filename, format, bytes, sha256)."""
    settings = get_settings()
    try:
        form = await request.form()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_multipart", "message": "The upload request is malformed."},
        ) from None

    files = [value for _key, value in form.multi_items() if isinstance(value, StarletteUploadFile)]
    if not files:
        raise _reject(
            UploadRejected(400, upload_service.CODE_MISSING_FILE, "No file was provided.")
        )
    if len(files) > settings.evidentia_upload_max_files:
        raise _reject(
            UploadRejected(
                400,
                upload_service.CODE_TOO_MANY_FILES,
                f"Upload at most {settings.evidentia_upload_max_files} file per request.",
            )
        )

    upload = files[0]
    filename = upload_service.sanitize_filename(upload.filename)
    try:
        data, digest = await upload_service.read_bounded(
            upload, settings.evidentia_upload_max_file_bytes
        )
        file_format = upload_service.detect_format(filename, upload.content_type, data[:16])
        upload_service.validate_text_payload(data)
    except UploadRejected as exc:
        raise _reject(exc) from None
    return filename, file_format, data, digest


def _upload_response(outcome: UploadOutcome) -> Dict[str, Any]:
    """Safe metadata only — no blob keys, paths, body text or queue details."""
    doc, version = outcome.document, outcome.version
    return {
        "documentId": doc.id,
        "versionId": version.id,
        "versionNo": version.version_no,
        "filename": doc.original_filename,
        "detectedFormat": _format_label(doc),
        "byteSize": doc.size_bytes,
        "status": doc.status,
        "stage": version.status,
        "createdAt": version.created_at.isoformat() if version.created_at else None,
        "duplicate": outcome.duplicate,
        "noop": outcome.noop,
        "retried": outcome.retried,
    }


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
):
    """Authenticated multipart MD/TXT upload. 202 = a new ingestion job was
    accepted; 200 = explicit duplicate (already in the library, nothing new
    stored)."""
    _require_corpus_enabled()
    enforce_upload(request, user_id=ctx.user_id, company_id=ctx.company_id)

    filename, file_format, data, digest = await _read_single_upload(request)

    try:
        outcome = upload_service.create_document_upload(
            db,
            company_id=ctx.company_id,
            user_id=ctx.user_id,
            filename=filename,
            file_format=file_format,
            data=data,
            digest=digest,
        )
    except UploadRejected as exc:
        db.rollback()
        raise _reject(exc) from None

    body = _upload_response(outcome)
    if not outcome.created:
        return JSONResponse(status_code=status.HTTP_200_OK, content=body)
    return body


@router.post("/{document_id}/versions", status_code=status.HTTP_202_ACCEPTED)
async def upload_new_version(
    document_id: str,
    request: Request,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
):
    """Explicitly upload a new version of an existing tenant document.
    Identical bytes are an explicit no-op (200); changed bytes create the
    immutable version N+1 (202) without touching older versions."""
    _require_corpus_enabled()
    enforce_upload(request, user_id=ctx.user_id, company_id=ctx.company_id)

    doc = documents_repo.get_document(db, document_id, ctx.company_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    filename, file_format, data, digest = await _read_single_upload(request)

    try:
        outcome = upload_service.create_new_version_upload(
            db,
            document=doc,
            user_id=ctx.user_id,
            filename=filename,
            file_format=file_format,
            data=data,
            digest=digest,
        )
    except UploadRejected as exc:
        db.rollback()
        raise _reject(exc) from None

    body = _upload_response(outcome)
    if not outcome.created:
        return JSONResponse(status_code=status.HTTP_200_OK, content=body)
    return body


@router.post("/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_document_ingestion(
    document_id: str,
    request: Request,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Re-enqueue the latest version when it failed. Reuses the stored bytes;
    never creates a duplicate version, blob or live job."""
    _require_corpus_enabled()
    enforce_upload(request, user_id=ctx.user_id, company_id=ctx.company_id)

    doc = documents_repo.get_document(db, document_id, ctx.company_id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        version = upload_service.retry_failed_version(db, document=doc)
    except UploadRejected as exc:
        db.rollback()
        raise _reject(exc) from None

    return {
        "documentId": doc.id,
        "versionId": version.id,
        "versionNo": version.version_no,
        "status": doc.status,
        "stage": version.status,
        "retried": True,
    }
