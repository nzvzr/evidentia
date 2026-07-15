"""Document endpoints. Tenant-scoped; the built-in corpus is read-only reference.

The demo corpus is still served as a *fallback* when the tenant has uploaded no
documents of its own, but it is shared reference material with no tenant rows
behind it — it is never writable and never mixes with another tenant's data.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.document_reader import list_documents as demo_documents
from app.api.deps import CompanyContext, get_company_context, require_admin
from app.core.config import get_settings
from app.db.session import get_db
from app.models.schemas import DocumentCreate
from app.repositories import documents as documents_repo

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "document"


def _serialize(doc) -> Dict[str, Any]:
    return {
        "id": doc.id,
        "companyId": doc.company_id,
        "title": doc.title,
        "slug": doc.slug,
        "type": doc.type,
        "category": doc.category,
        "metadata": doc.metadata_json,
        "createdAt": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("")
def get_documents(
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    if get_settings().is_db_enabled():
        rows = documents_repo.list_documents(db, ctx.company_id)
        if rows:
            return {"documents": [_serialize(r) for r in rows]}
    # Fallback: the built-in demo corpus metadata (shared read-only reference).
    return {"documents": demo_documents()}


@router.get("/{document_id}")
def get_document(
    document_id: str,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    doc = documents_repo.get_document(db, document_id, ctx.company_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return _serialize(doc)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_document(
    body: DocumentCreate,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
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
