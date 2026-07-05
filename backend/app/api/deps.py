"""Shared API dependencies/helpers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories import companies as companies_repo


def resolve_company_id(db: Session, company_id: str | None) -> str:
    """Return the given company id if valid, else the demo company (creating it)."""
    if company_id:
        existing = companies_repo.get_company(db, company_id)
        if existing:
            return existing.id
    company = companies_repo.get_or_create_demo_company(db)
    db.commit()
    return company.id
