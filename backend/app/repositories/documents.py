"""Document repository."""

from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import Document


def list_documents(db: Session, company_id: str) -> List[Document]:
    return list(
        db.execute(select(Document).where(Document.company_id == company_id).order_by(Document.created_at.desc()))
        .scalars()
        .all()
    )


def get_document(db: Session, document_id: str, company_id: str) -> Optional[Document]:
    """Tenant-scoped lookup. `company_id` is mandatory: a document belonging to
    another tenant is indistinguishable from one that does not exist."""
    return db.execute(
        select(Document).where(Document.id == document_id, Document.company_id == company_id)
    ).scalar_one_or_none()


def delete_document(db: Session, document_id: str, company_id: str) -> bool:
    row = get_document(db, document_id, company_id)
    if not row:
        return False
    db.delete(row)
    db.flush()
    return True


def create_document(
    db: Session,
    company_id: str,
    title: str,
    slug: str,
    doc_type: Optional[str] = None,
    category: Optional[str] = None,
    content_text: Optional[str] = None,
    metadata_json: Optional[dict[str, Any]] = None,
) -> Document:
    doc = Document(
        company_id=company_id,
        title=title,
        slug=slug,
        type=doc_type,
        category=category,
        content_text=content_text,
        metadata_json=metadata_json,
    )
    db.add(doc)
    db.flush()
    return doc
