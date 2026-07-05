"""Report CRUD endpoints. Stores/returns the full EvidentiaReport JSON."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import resolve_company_id
from app.core.config import get_settings
from app.db.session import get_db
from app.models.schemas import ReportCreate
from app.repositories import reports as reports_repo

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _serialize(report_row) -> Dict[str, Any]:
    # The stored report_json already carries the DB id and all report fields.
    data = dict(report_row.report_json or {})
    data["id"] = report_row.id
    data.setdefault("createdAt", report_row.created_at.isoformat() if report_row.created_at else None)
    return data


@router.get("")
def list_reports(company_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)) -> Dict[str, List[Dict[str, Any]]]:
    if not get_settings().is_db_enabled():
        return {"reports": []}
    cid = resolve_company_id(db, company_id)
    rows = reports_repo.list_reports(db, cid)
    return {"reports": [_serialize(r) for r in rows]}


@router.get("/{report_id}")
def get_report(report_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    if not get_settings().is_db_enabled():
        raise HTTPException(status_code=404, detail="Report not found")
    row = reports_repo.get_report(db, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return _serialize(row)


@router.post("")
def create_report(body: ReportCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    if not get_settings().is_db_enabled():
        raise HTTPException(status_code=503, detail="Database is disabled")
    cid = resolve_company_id(db, body.companyId)
    row = reports_repo.create_report(db, cid, body.report, user_id=body.userId, persona_id=body.personaId)
    return _serialize(row)


@router.delete("/{report_id}")
def delete_report(report_id: str, db: Session = Depends(get_db)) -> Dict[str, bool]:
    if not get_settings().is_db_enabled():
        raise HTTPException(status_code=503, detail="Database is disabled")
    ok = reports_repo.delete_report(db, report_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"ok": True}
