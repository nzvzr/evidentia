"""Company repository.

There is deliberately no `get_or_create_demo_company` and no global
`list_companies`: a company is only ever reachable through an explicit
membership (see `repositories.memberships`).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.db_models import Company


def get_company(db: Session, company_id: str) -> Optional[Company]:
    """Raw lookup by id. Callers MUST additionally verify membership — use
    `deps.get_company_context`, never this function alone, on request paths."""
    return db.get(Company, company_id)


def get_by_slug(db: Session, slug: str) -> Optional[Company]:
    return db.execute(select(Company).where(Company.slug == slug)).scalar_one_or_none()


def create_company(db: Session, name: str, slug: str, owner_id: Optional[str] = None) -> Company:
    company = Company(name=name, slug=slug, owner_id=owner_id)
    db.add(company)
    db.flush()
    return company


def set_owner_by_id(db: Session, company_id: str, owner_id: str) -> None:
    """Move the designated-owner pointer by id, as a direct UPDATE.

    Addressed by id on purpose. The previous `set_owner(db, company, owner_id)` took
    a `Company` *object*, and every caller passed the one a request dependency had
    loaded (`ctx.company`) — an instance whose `owner_id` was read before the lock
    was taken. Writing through a pre-lock object is how the designated owner ended up
    pointing at a demoted admin. Callers hold the company lock; the write is now
    independent of whatever the identity map happens to be holding.
    """
    db.execute(
        update(Company)
        .where(Company.id == company_id)
        .values(owner_id=owner_id)
        .execution_options(synchronize_session=False)
    )
    db.flush()
