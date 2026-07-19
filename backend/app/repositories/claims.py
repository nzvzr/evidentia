"""Persistence for report-local claim graphs and non-authoritative metrics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.claims.engine import ClaimRunResult
from app.models.db_models import (
    ClaimPatternVersion,
    PatternMetric,
    Report,
    ReportClaimCandidate,
    ReportClaimDecision,
    ReportClaimEvidence,
    ReportEvidenceBinding,
)


def _pattern_rows(db: Session, claim_run: ClaimRunResult) -> dict[str, ClaimPatternVersion]:
    raw_patterns = {item["id"]: item for item in claim_run.release.raw["patterns"]}
    result: dict[str, ClaimPatternVersion] = {}
    for spec in claim_run.release.specs:
        values = {
            "id": str(uuid.uuid4()),
            "claim_pack_id": claim_run.release.claim_pack_id,
            "claim_pack_version": claim_run.release.release_version,
            "module_id": spec.module,
            "module_version": claim_run.release.module_version,
            "claim_spec_id": spec.id,
            "pattern_version": spec.version,
            "schema_version": claim_run.release.schema_version,
            "release_version": claim_run.release.release_version,
            "release_digest": claim_run.release.release_digest,
            "pattern_digest": spec.pattern_digest,
            "definition_json": raw_patterns[spec.id],
            "imported_at": datetime.utcnow(),
        }
        dialect = db.get_bind().dialect.name
        insert = pg_insert(ClaimPatternVersion) if dialect == "postgresql" else sqlite_insert(ClaimPatternVersion)
        db.execute(insert.values(**values).on_conflict_do_nothing(
            index_elements=["claim_pack_id", "claim_spec_id", "pattern_version"]
        ))
        row = db.execute(
            select(ClaimPatternVersion).where(
                ClaimPatternVersion.claim_pack_id == claim_run.release.claim_pack_id,
                ClaimPatternVersion.claim_spec_id == spec.id,
                ClaimPatternVersion.pattern_version == spec.version,
            )
        ).scalar_one_or_none()
        if row is None:  # defensive: insert-or-select must always produce one row
            raise RuntimeError("claim pattern import failed")
        if (
            row.pattern_digest != spec.pattern_digest
            or row.release_digest != claim_run.release.release_digest
            or row.claim_pack_version != claim_run.release.release_version
            or row.module_id != spec.module
            or row.module_version != claim_run.release.module_version
        ):
            raise ValueError("immutable claim pattern identity changed without a version bump")
        result[spec.id] = row
    return result


def _increment_metrics(
    db: Session,
    *,
    company_id: str,
    pattern_id: str,
    pattern_row: ClaimPatternVersion,
    values: Mapping[str, int],
) -> None:
    columns = {
        "evaluated_count": int(values["evaluatedCount"]),
        "fired_count": int(values["firedCount"]),
        "candidate_count": int(values["candidateCount"]),
        "binding_count": int(values["bindingCount"]),
        "accepted_count": int(values["acceptedCount"]),
        "rejected_count": int(values["rejectedCount"]),
        "insufficient_evidence_count": int(values["insufficientEvidenceCount"]),
        "final_report_inclusion_count": int(values["finalReportInclusionCount"]),
        "llm_proposed_count": int(values["llmProposedCount"]),
    }
    dialect = db.get_bind().dialect.name
    insert = pg_insert(PatternMetric) if dialect == "postgresql" else sqlite_insert(PatternMetric)
    statement = insert.values(
        id=str(uuid.uuid4()),
        company_id=company_id,
        claim_pattern_version_id=pattern_row.id,
        updated_at=datetime.utcnow(),
        **columns,
    )
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=["company_id", "claim_pattern_version_id"],
        set_={
            name: getattr(PatternMetric.__table__.c, name) + getattr(excluded, name)
            for name in columns
        } | {"updated_at": datetime.utcnow()},
    )
    db.execute(statement)


def persist_claim_run(
    db: Session,
    *,
    report: Report,
    claim_run: ClaimRunResult,
    included_candidate_ids: set[str],
) -> None:
    pattern_rows = _pattern_rows(db, claim_run)
    bindings = {
        row.citation_id: row
        for row in db.execute(
            select(ReportEvidenceBinding).where(
                ReportEvidenceBinding.report_id == report.id,
                ReportEvidenceBinding.company_id == report.company_id,
            )
        ).scalars()
    }
    for item in claim_run.evaluated:
        candidate = item.candidate
        decision = item.decision
        candidate_row = ReportClaimCandidate(
            report_id=report.id,
            company_id=report.company_id,
            claim_pattern_version_id=pattern_rows[item.spec.id].id if item.spec is not None else None,
            candidate_id=candidate.candidate_id,
            claim_spec_id=candidate.claim_spec_id,
            pattern_version=candidate.pattern_version,
            candidate_source=candidate.candidate_source,
            proposed_statement=candidate.proposed_statement,
            source_snapshot_digest=candidate.source_snapshot_digest,
            matcher_observations=list(candidate.matcher_observations),
            deterministic_features=dict(candidate.deterministic_features),
            proposer_metadata=dict(candidate.proposer_metadata) if candidate.proposer_metadata else None,
            status_before_gate=candidate.status,
            appeared_in_final=candidate.candidate_id in included_candidate_ids,
        )
        db.add(candidate_row)
        db.flush()
        db.add(ReportClaimDecision(
            report_claim_candidate_id=candidate_row.id,
            report_id=report.id,
            company_id=report.company_id,
            decision=decision.decision,
            support_score=decision.support_score,
            threshold=decision.threshold,
            reason_codes=list(decision.reason_codes),
            matched_requirements=list(decision.matched_requirements),
            missing_requirements=list(decision.missing_requirements),
            conflicting_evidence=list(decision.conflicting_evidence),
            accepted_binding_ids=list(decision.accepted_binding_ids),
            gate_policy_id=decision.gate_policy_id,
            gate_policy_version=decision.gate_policy_version,
            gate_engine_version=decision.gate_engine_version,
            deterministic_features=dict(decision.deterministic_features),
        ))
        for citation_id in sorted(set(candidate.proposed_binding_ids)):
            binding = bindings.get(citation_id)
            if binding is None:
                continue
            db.add(ReportClaimEvidence(
                report_claim_candidate_id=candidate_row.id,
                report_evidence_binding_id=binding.id,
                report_id=report.id,
                company_id=report.company_id,
                proposed=True,
                accepted=citation_id in decision.accepted_binding_ids,
            ))
    for spec_id, values in claim_run.metrics.items():
        _increment_metrics(
            db,
            company_id=report.company_id,
            pattern_id=spec_id,
            pattern_row=pattern_rows[spec_id],
            values=values,
        )


def get_report_claims(db: Session, report_id: str, company_id: str) -> dict[str, Any] | None:
    report = db.execute(
        select(Report).where(
            Report.id == report_id,
            Report.company_id == company_id,
            Report.generation_status == "completed",
        )
    ).scalar_one_or_none()
    if report is None:
        return None
    candidates = list(db.execute(
        select(ReportClaimCandidate).where(
            ReportClaimCandidate.report_id == report_id,
            ReportClaimCandidate.company_id == company_id,
        ).order_by(ReportClaimCandidate.candidate_id.asc())
    ).scalars())
    decisions = {
        row.report_claim_candidate_id: row
        for row in db.execute(
            select(ReportClaimDecision).where(
                ReportClaimDecision.report_id == report_id,
                ReportClaimDecision.company_id == company_id,
            )
        ).scalars()
    }
    evidence_rows = list(db.execute(
        select(ReportClaimEvidence, ReportEvidenceBinding)
        .join(ReportEvidenceBinding, ReportEvidenceBinding.id == ReportClaimEvidence.report_evidence_binding_id)
        .where(
            ReportClaimEvidence.report_id == report_id,
            ReportClaimEvidence.company_id == company_id,
            ReportEvidenceBinding.company_id == company_id,
        )
    ).all())
    evidence_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for link, binding in evidence_rows:
        evidence_by_candidate.setdefault(link.report_claim_candidate_id, []).append({
            "citationId": binding.citation_id,
            "anchorId": binding.anchor_id,
            "documentVersionId": binding.document_version_id,
            "proposed": link.proposed,
            "accepted": link.accepted,
        })
    return {
        "claimEngineEnabled": bool(candidates),
        "candidates": [
            {
                "candidateId": candidate.candidate_id,
                "claimSpecId": candidate.claim_spec_id,
                "patternVersion": candidate.pattern_version,
                "candidateSource": candidate.candidate_source,
                "proposedStatement": candidate.proposed_statement,
                "sourceSnapshotDigest": candidate.source_snapshot_digest,
                "matcherObservations": candidate.matcher_observations,
                "proposerMetadata": candidate.proposer_metadata,
                "appearedInFinal": candidate.appeared_in_final,
                "decision": ({
                    "status": decisions[candidate.id].decision,
                    "supportScore": decisions[candidate.id].support_score,
                    "threshold": decisions[candidate.id].threshold,
                    "reasonCodes": decisions[candidate.id].reason_codes,
                    "matchedRequirements": decisions[candidate.id].matched_requirements,
                    "missingRequirements": decisions[candidate.id].missing_requirements,
                    "conflictingEvidence": decisions[candidate.id].conflicting_evidence,
                    "gatePolicyId": decisions[candidate.id].gate_policy_id,
                    "gatePolicyVersion": decisions[candidate.id].gate_policy_version,
                    "gateEngineVersion": decisions[candidate.id].gate_engine_version,
                    "features": decisions[candidate.id].deterministic_features,
                } if candidate.id in decisions else None),
                "evidenceBindings": sorted(
                    evidence_by_candidate.get(candidate.id, []), key=lambda value: value["citationId"]
                ),
            }
            for candidate in candidates
        ],
    }
