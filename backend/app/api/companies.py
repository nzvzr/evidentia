"""Company endpoints."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.schemas import CompanyCreate
from app.repositories import companies as companies_repo

router = APIRouter(prefix="/api/companies", tags=["companies"])


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "company"


def _serialize(company) -> Dict[str, Any]:
    return {
        "id": company.id,
        "name": company.name,
        "slug": company.slug,
        "createdAt": company.created_at.isoformat() if company.created_at else None,
    }


@router.get("")
def list_companies(db: Session = Depends(get_db)) -> Dict[str, List[Dict[str, Any]]]:
    return {"companies": [_serialize(c) for c in companies_repo.list_companies(db)]}


@router.post("")
def create_company(body: CompanyCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    slug = body.slug or _slugify(body.name)
    if companies_repo.get_by_slug(db, slug):
        raise HTTPException(status_code=409, detail="Company slug already exists")
    company = companies_repo.create_company(db, name=body.name, slug=slug)
    db.commit()
    db.refresh(company)
    return _serialize(company)
