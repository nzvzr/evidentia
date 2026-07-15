"""Persona endpoints. Tenant-scoped custom personas plus the default catalogue.

The default catalogue is static reference data (not tenant rows) and is appended
to every tenant's list; custom personas are always company-scoped.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.persona_mapper import PERSONA_PROFILES
from app.api.deps import CompanyContext, get_company_context, require_admin
from app.core.config import get_settings
from app.db.session import get_db
from app.models.schemas import PersonaCreate
from app.repositories import personas as personas_repo

router = APIRouter(prefix="/api/personas", tags=["personas"])


def _default_personas() -> List[Dict[str, Any]]:
    return [
        {
            "id": f"default-{p['key']}",
            "name": p["title"],
            "description": p["description"],
            "roleType": p["key"],
            "isDefault": True,
        }
        for p in PERSONA_PROFILES.values()
    ]


def _serialize(persona) -> Dict[str, Any]:
    return {
        "id": persona.id,
        "companyId": persona.company_id,
        "name": persona.name,
        "description": persona.description,
        "roleType": persona.role_type,
        "metadata": persona.metadata_json,
        "isDefault": False,
        "createdAt": persona.created_at.isoformat() if persona.created_at else None,
    }


@router.get("")
def get_personas(
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    custom: List[Dict[str, Any]] = []
    if get_settings().is_db_enabled():
        custom = [_serialize(p) for p in personas_repo.list_personas(db, ctx.company_id)]
    return {"personas": custom + _default_personas()}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_persona(
    body: PersonaCreate,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    persona = personas_repo.create_persona(
        db,
        company_id=ctx.company_id,  # from the session, not the request body
        name=body.name,
        description=body.description,
        role_type=body.roleType,
        metadata_json=body.metadata,
    )
    db.commit()
    db.refresh(persona)
    return _serialize(persona)


@router.delete("/{persona_id}")
def delete_persona(
    persona_id: str,
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Dict[str, bool]:
    if not personas_repo.delete_persona(db, persona_id, ctx.company_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
    db.commit()
    return {"ok": True}
