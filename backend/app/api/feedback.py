"""Authenticated, tenant-scoped M5a feedback intake."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import CompanyContext, get_company_context
from app.api.limits import enforce_feedback
from app.db.session import get_db
from app.repositories import feedback as feedback_repo

router = APIRouter(prefix="/api/reports", tags=["feedback"])

ReasonCode = Annotated[str | None, Field(default=None, max_length=80, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReportFeedbackBody(StrictBody):
    verdict: Literal["correct_useful", "partially_correct", "incorrect"]
    reasonCode: ReasonCode = None
    privateText: Annotated[str | None, Field(default=None, max_length=2000)] = None


class ItemFeedbackBody(StrictBody):
    itemPath: Annotated[str, Field(min_length=1, max_length=300)]
    itemType: Literal["workflow_step", "risk", "citation", "suggested_action"]
    verdict: Literal["accepted", "rejected", "edited", "insufficient_evidence"]
    reasonCode: ReasonCode = None
    editedText: Annotated[str | None, Field(default=None, max_length=4000)] = None


class CitationFeedbackBody(StrictBody):
    itemPath: Annotated[str, Field(min_length=1, max_length=300)]
    citationId: Annotated[str, Field(min_length=1, max_length=120)]
    verdict: Literal["correct", "irrelevant", "incorrect_source"]
    correctedAnchorId: Annotated[str | None, Field(default=None, max_length=120)] = None


class RetrievalMissBody(StrictBody):
    candidateId: Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
    evidenceNeedId: Annotated[str, Field(min_length=1, max_length=120)]
    correctedAnchorId: Annotated[str, Field(min_length=1, max_length=120)]


def _error(exc: feedback_repo.FeedbackValidationError) -> HTTPException:
    if str(exc) == "report_not_found":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": str(exc), "message": "Feedback references are invalid."},
    )


@router.get("/{report_id}/feedback")
def get_feedback(
    report_id: str,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
):
    try:
        return feedback_repo.get_feedback(
            db, report_id=report_id, company_id=ctx.company_id, user_id=ctx.user_id
        )
    except feedback_repo.FeedbackValidationError as exc:
        raise _error(exc) from None


@router.put("/{report_id}/feedback")
def put_report_feedback(
    report_id: str,
    body: ReportFeedbackBody,
    request: Request,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
):
    enforce_feedback(request, ctx.user_id, ctx.company_id)
    try:
        feedback_repo.put_report_feedback(
            db, report_id=report_id, company_id=ctx.company_id, user_id=ctx.user_id,
            verdict=body.verdict, reason_code=body.reasonCode, private_text=body.privateText,
        )
    except feedback_repo.FeedbackValidationError as exc:
        raise _error(exc) from None
    return {"ok": True, "replacement": True}


@router.put("/{report_id}/feedback/items")
def put_item_feedback(
    report_id: str,
    body: ItemFeedbackBody,
    request: Request,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
):
    enforce_feedback(request, ctx.user_id, ctx.company_id)
    try:
        feedback_repo.put_item_feedback(
            db, report_id=report_id, company_id=ctx.company_id, user_id=ctx.user_id,
            item_path=body.itemPath, item_type=body.itemType, verdict=body.verdict,
            reason_code=body.reasonCode, edited_text=body.editedText,
        )
    except feedback_repo.FeedbackValidationError as exc:
        raise _error(exc) from None
    return {"ok": True, "replacement": True}


@router.put("/{report_id}/feedback/citations")
def put_citation_feedback(
    report_id: str,
    body: CitationFeedbackBody,
    request: Request,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
):
    enforce_feedback(request, ctx.user_id, ctx.company_id)
    try:
        feedback_repo.put_citation_feedback(
            db, report_id=report_id, company_id=ctx.company_id, user_id=ctx.user_id,
            item_path=body.itemPath, citation_id=body.citationId, verdict=body.verdict,
            corrected_anchor_id=body.correctedAnchorId,
        )
    except feedback_repo.FeedbackValidationError as exc:
        raise _error(exc) from None
    return {"ok": True, "replacement": True}


@router.put("/{report_id}/retrieval-misses")
def put_retrieval_miss(
    report_id: str,
    body: RetrievalMissBody,
    request: Request,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
):
    enforce_feedback(request, ctx.user_id, ctx.company_id)
    try:
        feedback_repo.put_retrieval_miss(
            db, report_id=report_id, company_id=ctx.company_id, user_id=ctx.user_id,
            candidate_id=body.candidateId, evidence_need_id=body.evidenceNeedId,
            corrected_anchor_id=body.correctedAnchorId,
        )
    except feedback_repo.FeedbackValidationError as exc:
        raise _error(exc) from None
    return {"ok": True, "replacement": True}
