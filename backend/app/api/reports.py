"""Report CRUD endpoints. Stores/returns the full EvidentiaReport JSON.

Every handler is tenant-scoped through `CompanyContext`. The report id is never
sufficient on its own to reach a row — see `repositories.reports.get_report`,
which requires a company_id.

The public EvidentiaReport schema is unchanged: `_serialize` returns exactly the
stored report_json plus `id`/`createdAt`, as before.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import CompanyContext, get_company_context, require_admin
from app.core.config import get_settings
from app.db.session import get_db
from app.repositories import reports as reports_repo

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _serialize(report_row) -> Dict[str, Any]:
    # The stored report_json already carries the DB id and all report fields.
    data = dict(report_row.report_json or {})
    data["id"] = report_row.id
    data.setdefault("createdAt", report_row.created_at.isoformat() if report_row.created_at else None)
    return data


@router.get("")
def list_reports(
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    if not get_settings().is_db_enabled():
        return {"reports": []}
    rows = reports_repo.list_reports(db, ctx.company_id)
    return {"reports": [_serialize(r) for r in rows]}


@router.get("/{report_id}")
def get_report(
    report_id: str,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if not get_settings().is_db_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    # Scoped by company: another tenant's report id yields 404, not the report.
    row = reports_repo.get_report(db, report_id, ctx.company_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return _serialize(row)


@router.get("/{report_id}/sources")
def get_report_sources(
    report_id: str,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Tenant-scoped audit projection; public report JSON remains unchanged."""
    if not get_settings().is_db_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    data = reports_repo.get_report_sources(db, report_id, ctx.company_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return data


@router.post("", status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
def create_report() -> Dict[str, Any]:
    """Removed. Reports are created **only** by authenticated generation.

    This endpoint accepted an arbitrary JSON blob and stored it as a report. That
    made every trust signal in the product forgeable: a client could persist a
    report claiming `generationMode: "llm-assisted"`, a 100% confidence score, and
    citations that no pipeline ever produced — indistinguishable, downstream, from
    a genuinely grounded report. Nothing validated the schema, and `personaId` was
    never checked against the caller's tenant.

    There is no legitimate caller: the frontend never used it (the backend
    persists during generation). It is kept as an explicit 405 rather than deleted
    so an old client gets a clear answer instead of a 404 that reads like a bug.
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Reports are created by POST /api/generate-workflow only.",
    )


@router.delete("/{report_id}")
def delete_report(
    report_id: str,
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Dict[str, bool]:
    """Deletion requires admin or owner — a plain member cannot destroy tenant data."""
    if not get_settings().is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is disabled")
    ok = reports_repo.delete_report(db, report_id, ctx.company_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return {"ok": True}
