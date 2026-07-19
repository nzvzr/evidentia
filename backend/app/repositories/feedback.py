"""Tenant-scoped feedback intake with replacement semantics."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.db_models import (
    CitationFeedback,
    DocumentSection,
    ItemFeedback,
    Report,
    ReportClaimCandidate,
    ReportClaimDecision,
    ReportEvidenceBinding,
    ReportFeedback,
    ReportSourceVersion,
    RetrievalMiss,
)

_ITEM_PATH = re.compile(
    r"\A/(workflowSteps|risks|citations|suggestedActions)/(0|[1-9][0-9]*)\Z",
    re.ASCII,
)
_ITEM_TYPES = {
    "workflowSteps": "workflow_step",
    "risks": "risk",
    "citations": "citation",
    "suggestedActions": "suggested_action",
}


class FeedbackValidationError(ValueError):
    pass


def _report(db: Session, report_id: str, company_id: str) -> Report:
    row = db.execute(select(Report).where(
        Report.id == report_id,
        Report.company_id == company_id,
        Report.generation_status == "completed",
    )).scalar_one_or_none()
    if row is None:
        raise FeedbackValidationError("report_not_found")
    return row


def validate_item_path(report: Report, item_path: str, item_type: str) -> Any:
    match = _ITEM_PATH.fullmatch(item_path or "")
    if match is None or _ITEM_TYPES[match.group(1)] != item_type:
        raise FeedbackValidationError("invalid_item_path")
    values = (report.report_json or {}).get(match.group(1))
    index = int(match.group(2))
    if not isinstance(values, list) or index >= len(values):
        raise FeedbackValidationError("invalid_item_path")
    return values[index]


def _upsert(db: Session, model: Any, values: dict[str, Any], conflict: list[str], updates: list[str]) -> None:
    dialect = db.get_bind().dialect.name
    insert = pg_insert(model) if dialect == "postgresql" else sqlite_insert(model)
    statement = insert.values(id=str(uuid.uuid4()), created_at=datetime.utcnow(), updated_at=datetime.utcnow(), **values)
    statement = statement.on_conflict_do_update(
        index_elements=conflict,
        set_={key: getattr(statement.excluded, key) for key in updates} | {"updated_at": datetime.utcnow()},
    )
    db.execute(statement)


def put_report_feedback(
    db: Session, *, report_id: str, company_id: str, user_id: str,
    verdict: str, reason_code: str | None, private_text: str | None,
) -> None:
    _report(db, report_id, company_id)
    _upsert(db, ReportFeedback, {
        "report_id": report_id, "company_id": company_id, "user_id": user_id,
        "verdict": verdict, "reason_code": reason_code, "private_text": private_text,
    }, ["report_id", "user_id"], ["verdict", "reason_code", "private_text"])
    db.commit()


def put_item_feedback(
    db: Session, *, report_id: str, company_id: str, user_id: str,
    item_path: str, item_type: str, verdict: str, reason_code: str | None,
    edited_text: str | None,
) -> None:
    report = _report(db, report_id, company_id)
    validate_item_path(report, item_path, item_type)
    if verdict == "edited" and not edited_text:
        raise FeedbackValidationError("edited_text_required")
    _upsert(db, ItemFeedback, {
        "report_id": report_id, "company_id": company_id, "user_id": user_id,
        "item_path": item_path, "item_type": item_type, "verdict": verdict,
        "reason_code": reason_code, "edited_text": edited_text,
    }, ["report_id", "user_id", "item_path"], ["item_type", "verdict", "reason_code", "edited_text"])
    db.commit()


def _binding(db: Session, report_id: str, company_id: str, citation_id: str) -> ReportEvidenceBinding:
    row = db.execute(select(ReportEvidenceBinding).where(
        ReportEvidenceBinding.report_id == report_id,
        ReportEvidenceBinding.company_id == company_id,
        ReportEvidenceBinding.citation_id == citation_id,
    )).scalar_one_or_none()
    if row is None:
        raise FeedbackValidationError("invalid_citation")
    return row


def _corrected_section(
    db: Session, *, report_id: str, company_id: str, anchor_id: str | None,
) -> DocumentSection | None:
    if not anchor_id:
        return None
    version_ids = select(ReportSourceVersion.document_version_id).where(
        ReportSourceVersion.report_id == report_id,
        ReportSourceVersion.company_id == company_id,
    )
    rows = list(db.execute(select(DocumentSection).where(
        DocumentSection.company_id == company_id,
        DocumentSection.version_id.in_(version_ids),
        DocumentSection.anchor_id == anchor_id,
    )).scalars())
    if len(rows) != 1:
        raise FeedbackValidationError("invalid_corrected_anchor")
    return rows[0]


def _corrected_binding(
    db: Session, *, report_id: str, company_id: str, anchor_id: str | None,
) -> ReportEvidenceBinding | None:
    if not anchor_id:
        return None
    rows = list(db.execute(select(ReportEvidenceBinding).where(
        ReportEvidenceBinding.report_id == report_id,
        ReportEvidenceBinding.company_id == company_id,
        ReportEvidenceBinding.anchor_id == anchor_id,
    )).scalars())
    if len(rows) != 1:
        raise FeedbackValidationError("invalid_corrected_anchor")
    return rows[0]


def put_citation_feedback(
    db: Session, *, report_id: str, company_id: str, user_id: str,
    item_path: str, citation_id: str, verdict: str, corrected_anchor_id: str | None,
) -> None:
    report = _report(db, report_id, company_id)
    item_type = _ITEM_TYPES.get((_ITEM_PATH.fullmatch(item_path or "") or [None, ""])[1], "")
    if item_type not in {"workflow_step", "risk", "citation"}:
        raise FeedbackValidationError("invalid_item_path")
    item = validate_item_path(report, item_path, item_type)
    if item_type == "citation":
        offered = item.get("id") if isinstance(item, dict) else None
    else:
        offered = item.get("evidenceCode") if isinstance(item, dict) else None
    if offered != citation_id:
        raise FeedbackValidationError("invalid_citation")
    binding = _binding(db, report_id, company_id, citation_id)
    corrected = _corrected_binding(
        db, report_id=report_id, company_id=company_id, anchor_id=corrected_anchor_id
    )
    if verdict == "incorrect_source" and corrected is None:
        raise FeedbackValidationError("corrected_anchor_required")
    values = {
        "report_id": report_id, "company_id": company_id, "user_id": user_id,
        "report_evidence_binding_id": binding.id, "item_path": item_path,
        "citation_id": citation_id, "verdict": verdict,
        "corrected_report_evidence_binding_id": corrected.id if corrected else None,
    }
    _upsert(db, CitationFeedback, values, ["report_id", "user_id", "item_path", "citation_id"], [
        "report_evidence_binding_id", "verdict", "corrected_report_evidence_binding_id",
    ])
    db.commit()


def put_retrieval_miss(
    db: Session, *, report_id: str, company_id: str, user_id: str,
    candidate_id: str, evidence_need_id: str, corrected_anchor_id: str,
) -> None:
    _report(db, report_id, company_id)
    candidate = db.execute(select(ReportClaimCandidate).where(
        ReportClaimCandidate.report_id == report_id,
        ReportClaimCandidate.company_id == company_id,
        ReportClaimCandidate.candidate_id == candidate_id,
    )).scalar_one_or_none()
    if candidate is None:
        raise FeedbackValidationError("invalid_claim_candidate")
    decision = db.execute(select(ReportClaimDecision).where(
        ReportClaimDecision.report_claim_candidate_id == candidate.id,
        ReportClaimDecision.report_id == report_id,
        ReportClaimDecision.company_id == company_id,
    )).scalar_one_or_none()
    if decision is None or decision.decision == "accepted" or evidence_need_id not in (decision.missing_requirements or []):
        raise FeedbackValidationError("invalid_evidence_need")
    corrected = _corrected_section(
        db, report_id=report_id, company_id=company_id, anchor_id=corrected_anchor_id
    )
    if corrected is None:
        raise FeedbackValidationError("invalid_corrected_anchor")
    _upsert(db, RetrievalMiss, {
        "report_id": report_id, "company_id": company_id, "user_id": user_id,
        "report_claim_candidate_id": candidate.id, "claim_spec_id": candidate.claim_spec_id,
        "pattern_version": candidate.pattern_version, "evidence_need_id": evidence_need_id,
        "corrected_section_id": corrected.id, "corrected_version_id": corrected.version_id,
        "corrected_document_id": corrected.document_id, "corrected_anchor_id": corrected.anchor_id,
    }, ["report_id", "user_id", "report_claim_candidate_id", "evidence_need_id"], [
        "corrected_section_id", "corrected_version_id",
        "corrected_document_id", "corrected_anchor_id",
    ])
    db.commit()


def get_feedback(db: Session, *, report_id: str, company_id: str, user_id: str) -> dict[str, Any]:
    _report(db, report_id, company_id)
    report_row = db.execute(select(ReportFeedback).where(
        ReportFeedback.report_id == report_id,
        ReportFeedback.company_id == company_id,
        ReportFeedback.user_id == user_id,
    )).scalar_one_or_none()
    items = list(db.execute(select(ItemFeedback).where(
        ItemFeedback.report_id == report_id,
        ItemFeedback.company_id == company_id,
        ItemFeedback.user_id == user_id,
    )).scalars())
    citations = list(db.execute(select(CitationFeedback).where(
        CitationFeedback.report_id == report_id,
        CitationFeedback.company_id == company_id,
        CitationFeedback.user_id == user_id,
    )).scalars())
    corrected_ids = {
        row.corrected_report_evidence_binding_id
        for row in citations
        if row.corrected_report_evidence_binding_id
    }
    corrected_anchors = {
        row.id: row.anchor_id
        for row in db.execute(select(ReportEvidenceBinding).where(
            ReportEvidenceBinding.report_id == report_id,
            ReportEvidenceBinding.company_id == company_id,
            ReportEvidenceBinding.id.in_(corrected_ids),
        )).scalars()
    } if corrected_ids else {}
    return {
        "report": None if report_row is None else {
            "verdict": report_row.verdict,
            "reasonCode": report_row.reason_code,
            "privateText": report_row.private_text,
        },
        "items": [{
            "itemPath": row.item_path, "itemType": row.item_type, "verdict": row.verdict,
            "reasonCode": row.reason_code, "editedText": row.edited_text,
        } for row in sorted(items, key=lambda value: value.item_path)],
        "citations": [{
            "itemPath": row.item_path, "citationId": row.citation_id, "verdict": row.verdict,
            "correctedAnchorId": corrected_anchors.get(row.corrected_report_evidence_binding_id),
        } for row in sorted(citations, key=lambda value: (value.item_path, value.citation_id))],
    }
