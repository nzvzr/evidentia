"""Document endpoints. Returns DB documents if present, else the demo corpus."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agents.document_reader import list_documents as demo_documents
from app.api.deps import resolve_company_id
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
def get_documents(company_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)) -> Dict[str, List[Dict[str, Any]]]:
    if get_settings().is_db_enabled():
        cid = resolve_company_id(db, company_id)
        rows = documents_repo.list_documents(db, cid)
        if rows:
            return {"documents": [_serialize(r) for r in rows]}
    # Fallback: the built-in demo corpus metadata.
    return {"documents": demo_documents()}


@router.post("")
def create_document(body: DocumentCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    cid = resolve_company_id(db, body.companyId)
    doc = documents_repo.create_document(
        db,
        company_id=cid,
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
