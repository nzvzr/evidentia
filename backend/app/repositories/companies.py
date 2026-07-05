"""Company repository."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import Company

DEMO_COMPANY_NAME = "Northreach Cloud"
DEMO_COMPANY_SLUG = "northreach-cloud"


def get_company(db: Session, company_id: str) -> Optional[Company]:
    return db.get(Company, company_id)


def get_by_slug(db: Session, slug: str) -> Optional[Company]:
    return db.execute(select(Company).where(Company.slug == slug)).scalar_one_or_none()


def list_companies(db: Session) -> List[Company]:
    return list(db.execute(select(Company)).scalars().all())


def create_company(db: Session, name: str, slug: str) -> Company:
    company = Company(name=name, slug=slug)
    db.add(company)
    db.flush()
    return company


def get_or_create_demo_company(db: Session) -> Company:
    existing = get_by_slug(db, DEMO_COMPANY_SLUG)
    if existing:
        return existing
    return create_company(db, DEMO_COMPANY_NAME, DEMO_COMPANY_SLUG)
