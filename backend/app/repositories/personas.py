"""Persona repository."""

from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import Persona


def list_personas(db: Session, company_id: str) -> List[Persona]:
    return list(
        db.execute(select(Persona).where(Persona.company_id == company_id).order_by(Persona.created_at.desc()))
        .scalars()
        .all()
    )


def get_persona(db: Session, persona_id: str, company_id: str) -> Optional[Persona]:
    """Tenant-scoped lookup. `company_id` is mandatory — see documents repo."""
    return db.execute(
        select(Persona).where(Persona.id == persona_id, Persona.company_id == company_id)
    ).scalar_one_or_none()


def delete_persona(db: Session, persona_id: str, company_id: str) -> bool:
    row = get_persona(db, persona_id, company_id)
    if not row:
        return False
    db.delete(row)
    db.flush()
    return True


def create_persona(
    db: Session,
    company_id: str,
    name: str,
    description: Optional[str] = None,
    role_type: Optional[str] = None,
    metadata_json: Optional[dict[str, Any]] = None,
) -> Persona:
    persona = Persona(
        company_id=company_id,
        name=name,
        description=description,
        role_type=role_type,
        metadata_json=metadata_json,
    )
    db.add(persona)
    db.flush()
    return persona
