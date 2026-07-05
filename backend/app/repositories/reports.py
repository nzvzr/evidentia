"""Report repository. Stores the full EvidentiaReport in report_json."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import Report


def list_reports(db: Session, company_id: str) -> List[Report]:
    return list(
        db.execute(select(Report).where(Report.company_id == company_id).order_by(Report.created_at.desc()))
        .scalars()
        .all()
    )


def get_report(db: Session, report_id: str) -> Optional[Report]:
    return db.get(Report, report_id)


def create_report(
    db: Session,
    company_id: str,
    report: Dict[str, Any],
    user_id: Optional[str] = None,
    persona_id: Optional[str] = None,
) -> Report:
    """Persist a generated EvidentiaReport. The stored report_json's `id` is
    aligned to the new DB row id so the frontend can fetch it back by id."""
    metrics = report.get("metrics") or {}
    row = Report(
        company_id=company_id,
        user_id=user_id,
        persona_id=persona_id,
        title=report.get("persona") and f"{report.get('persona')} · {report.get('market')}" or "Report",
        market=report.get("market"),
        persona_name=report.get("persona"),
        custom_persona=report.get("customPersona"),
        generation_mode=report.get("generationMode"),
        llm_provider=report.get("llmProvider"),
        llm_model=report.get("llmModel"),
        confidence=report.get("confidence") or metrics.get("confidence"),
        report_json=report,
    )
    db.add(row)
    db.flush()  # assigns row.id
    # Align the stored JSON's id to the DB id and persist the update.
    aligned = {**report, "id": row.id}
    row.report_json = aligned
    db.commit()
    db.refresh(row)
    return row


def delete_report(db: Session, report_id: str) -> bool:
    row = db.get(Report, report_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
