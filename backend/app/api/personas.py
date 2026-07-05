"""Persona endpoints. Returns company personas plus the default catalogue."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agents.persona_mapper import PERSONA_PROFILES
from app.api.deps import resolve_company_id
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
def get_personas(company_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)) -> Dict[str, List[Dict[str, Any]]]:
    custom: List[Dict[str, Any]] = []
    if get_settings().is_db_enabled():
        cid = resolve_company_id(db, company_id)
        custom = [_serialize(p) for p in personas_repo.list_personas(db, cid)]
    return {"personas": custom + _default_personas()}


@router.post("")
def create_persona(body: PersonaCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    cid = resolve_company_id(db, body.companyId)
    persona = personas_repo.create_persona(
        db,
        company_id=cid,
        name=body.name,
        description=body.description,
        role_type=body.roleType,
        metadata_json=body.metadata,
    )
    db.commit()
    db.refresh(persona)
    return _serialize(persona)
