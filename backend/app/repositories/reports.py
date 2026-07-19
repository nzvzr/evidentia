"""Tenant-scoped report persistence, M4 provenance and evidence bindings."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.section_provider import (
    GENERATION_ENGINE_VERSION,
    RETRIEVAL_ENGINE_VERSION,
    TenantCorpusProvider,
)
from app.models.db_models import Report, ReportEvidenceBinding, ReportSourceVersion
from app.repositories.claims import persist_claim_run

_DEMO_CITATION_PREFIXES = frozenset({"DEMO"})


class EvidenceValidationError(ValueError):
    pass


def list_reports(db: Session, company_id: str) -> List[Report]:
    return list(
        db.execute(
            select(Report)
            .where(Report.company_id == company_id, Report.generation_status == "completed")
            .order_by(Report.created_at.desc())
        )
        .scalars()
        .all()
    )


def get_report(db: Session, report_id: str, company_id: str) -> Optional[Report]:
    """Tenant-scoped lookup. `company_id` is mandatory: this is what closes the
    report IDOR — a report id from another tenant resolves to None (→ 404)."""
    return db.execute(
        select(Report).where(
            Report.id == report_id,
            Report.company_id == company_id,
            Report.generation_status == "completed",
        )
    ).scalar_one_or_none()


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


def _engine_versions(provider: TenantCorpusProvider, telemetry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    telemetry = telemetry or {}
    anchors = sorted({source.anchor_algo_version for source in provider.source_versions})
    llm_calls = int(telemetry.get("llmCalls") or 0)
    result: Dict[str, Any] = {
        "engineRelease": GENERATION_ENGINE_VERSION,
        "modules": [],
        "patternLibrary": "pre-m5-static-v1",
        "signaturePacks": [],
        "taxonomies": [],
        "thresholdPolicy": "evidence-support-v1",
        "anchorAlgo": anchors,
        "benchmark": "v1",
        "retrieval": {
            "strategy": "scoped-lexical",
            "version": RETRIEVAL_ENGINE_VERSION,
            "config": provider.config.config_version,
            "snapshotDigest": provider.snapshot_digest,
        },
        "tenantGlossary": None,
    }
    if llm_calls > 0:
        result["llm"] = {
            "provider": telemetry.get("provider"),
            "model": telemetry.get("model"),
            "promptVersion": telemetry.get("promptVersion"),
        }
    claim = telemetry.get("claimEngine") or {}
    if claim.get("enabled"):
        result["modules"] = [{"id": "compliance", "version": "1.0.0"}]
        result["patternLibrary"] = {
            "id": claim.get("claimPackId"),
            "schemaVersion": claim.get("schemaVersion"),
            "version": claim.get("releaseVersion"),
            "digest": claim.get("releaseDigest"),
            "matcherEngineVersion": claim.get("matcherEngineVersion"),
        }
        result["thresholdPolicy"] = {
            "gateEngineVersion": claim.get("gateEngineVersion"),
            "policies": [
                {
                    "claimSpecId": claim_spec_id,
                    "policyId": policy_id,
                    "policyVersion": policy_version,
                    "threshold": threshold,
                }
                for claim_spec_id, policy_id, policy_version, threshold in sorted({
                    (
                        decision.get("claimSpecId"),
                        decision.get("gatePolicyId"),
                        decision.get("gatePolicyVersion"),
                        decision.get("threshold"),
                    )
                    for decision in claim.get("decisions", [])
                })
            ],
        }
    return result


def create_generation_run(
    db: Session,
    *,
    company_id: str,
    user_id: str,
    market: str,
    persona: str,
    custom_persona: str,
    provider: TenantCorpusProvider,
) -> Report:
    """Persist the frozen version set and evidence registry, then commit.

    The commit is intentionally before orchestration/LLM execution: no DB lock
    or transaction remains open while an external model may run.
    """
    row = Report(
        company_id=company_id,
        user_id=user_id,
        title=f"{custom_persona or persona} · {market}",
        market=market,
        persona_name=persona,
        custom_persona=custom_persona or None,
        report_json={},
        source_versions=provider.source_versions_json(),
        engine_versions=_engine_versions(provider),
        corpus_mode="tenant",
        corpus_snapshot_digest=provider.snapshot_digest,
        retrieval_engine_version=RETRIEVAL_ENGINE_VERSION,
        orchestrator_version=GENERATION_ENGINE_VERSION,
        generation_status="running",
        source_version_count=len(provider.source_versions),
        evidence_section_count=len(provider.evidence),
    )
    db.add(row)
    db.flush()

    source_rows: Dict[str, ReportSourceVersion] = {}
    for source in provider.source_versions:
        bound = ReportSourceVersion(
            report_id=row.id,
            company_id=company_id,
            document_id=source.document_id,
            document_version_id=source.document_version_id,
            version_no=source.version_no,
            manifest_sha256=source.manifest_sha256,
            finalization_target_digest=source.finalization_target_digest,
            position=source.position,
        )
        db.add(bound)
        db.flush()
        source_rows[source.document_version_id] = bound

    for evidence in provider.evidence:
        source = source_rows[evidence.document_version_id]
        db.add(
            ReportEvidenceBinding(
                report_id=row.id,
                company_id=company_id,
                report_source_version_id=source.id,
                document_id=evidence.document_id,
                document_version_id=evidence.document_version_id,
                section_id=evidence.section_id,
                anchor_id=evidence.anchor_id,
                citation_id=evidence.citation_id,
                section_ordinal=evidence.section_ordinal,
                section_signature=evidence.section_signature,
                retrieval_rank=evidence.retrieval_rank,
                retrieval_score=evidence.retrieval_score,
                selected_for_prompt=True,
                cited_in_final=False,
                evidence_excerpt=evidence.excerpt,
                text_sha256=evidence.text_sha256,
                document_title=evidence.document_title,
                original_filename=evidence.original_filename,
                section_title=evidence.section_title,
                heading_path=list(evidence.heading_path),
            )
        )
    db.commit()
    db.refresh(row)
    return row


def _all_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _all_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_strings(child)


def _citation_prefix(evidence: Any) -> str:
    suffix = f"-{evidence.anchor_id}"
    if not evidence.citation_id.endswith(suffix):
        raise EvidenceValidationError("citation identity does not match its bound anchor")
    return evidence.citation_id[: -len(suffix)]


def _validate_narrative_citation_namespaces(
    value: Any,
    *,
    allowed: set[str],
    citation_prefixes: set[str] | frozenset[str],
) -> None:
    """Reject unknown IDs only in citation namespaces known to this run.

    Standards and ordinary hyphenated tokens remain narrative text unless their
    prefix is an actual generation citation family. Structured citation fields
    are validated separately and exactly.
    """
    if not citation_prefixes:
        return
    family = "|".join(sorted((re.escape(prefix) for prefix in citation_prefixes), key=lambda v: (-len(v), v)))
    citation_re = re.compile(
        rf"(?<![A-Za-z0-9])(?:{family})-[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?![A-Za-z0-9-])"
    )
    for text in _all_strings(value):
        for candidate in citation_re.findall(text):
            if candidate not in allowed:
                raise EvidenceValidationError("report text emitted an unknown citation identity")


def validate_tenant_report(report: Dict[str, Any], provider: TenantCorpusProvider) -> set[str]:
    """Validate the final report against the one frozen citation registry."""
    registry = {evidence.citation_id: evidence for evidence in provider.evidence}
    if len(registry) != len(provider.evidence):
        raise EvidenceValidationError("ambiguous citation registry")

    cited: set[str] = set()
    for item in [*report.get("workflowSteps", []), *report.get("risks", [])]:
        code = item.get("evidenceCode")
        if code == "N/A":
            continue
        if not isinstance(code, str) or code not in registry:
            raise EvidenceValidationError("report emitted a citation outside the snapshot")
        cited.add(code)

    for citation in report.get("citations", []):
        code = citation.get("id")
        if not isinstance(code, str) or code not in registry:
            raise EvidenceValidationError("report emitted a citation outside the snapshot")
        evidence = registry[code]
        if (
            citation.get("section") != evidence.section_title
            or citation.get("excerpt") != evidence.excerpt
            or citation.get("source") != f"{evidence.document_title} · {evidence.section_title}"
        ):
            raise EvidenceValidationError("citation display data does not match its bound section")
        cited.add(code)

    # Defence in depth against prompt text asking the model to print an invented
    # code in narrative fields (formal evidence fields above are authoritative).
    # Scope recognition to this report's tenant prefixes plus the known demo
    # families; a global citation-shaped heuristic rejects real standards.
    allowed = set(registry) | {"N/A"}
    narrative_projection = {key: value for key, value in report.items() if key != "citations"}
    tenant_prefixes = {_citation_prefix(evidence) for evidence in provider.evidence}
    _validate_narrative_citation_namespaces(
        narrative_projection,
        allowed=allowed,
        citation_prefixes=tenant_prefixes | _DEMO_CITATION_PREFIXES,
    )
    return cited


def complete_generation_run(
    db: Session,
    row: Report,
    report: Dict[str, Any],
    telemetry: Dict[str, Any],
    provider: TenantCorpusProvider,
) -> Report:
    cited = validate_tenant_report(report, provider)
    metrics = report.get("metrics") or {}
    row.title = report.get("persona") and f"{report.get('persona')} · {report.get('market')}" or "Report"
    row.persona_name = report.get("persona")
    row.generation_mode = report.get("generationMode")
    row.execution_mode = report.get("generationMode")
    row.llm_provider = telemetry.get("provider") if telemetry.get("llmCalls", 0) else "none"
    row.llm_model = telemetry.get("model") if telemetry.get("llmCalls", 0) else None
    row.confidence = report.get("confidence") or metrics.get("confidence")
    row.engine_versions = _engine_versions(provider, telemetry)
    row.generation_status = "completed"
    row.generation_error_code = None
    aligned = {**report, "id": row.id}
    row.report_json = aligned
    bindings = list(
        db.execute(
            select(ReportEvidenceBinding).where(
                ReportEvidenceBinding.report_id == row.id,
                ReportEvidenceBinding.company_id == row.company_id,
            )
        ).scalars()
    )
    for binding in bindings:
        binding.cited_in_final = binding.citation_id in cited
    claim_run = telemetry.get("_claimRunResult")
    if claim_run is not None:
        persist_claim_run(
            db,
            report=row,
            claim_run=claim_run,
            included_candidate_ids=set(telemetry.get("_includedClaimCandidateIds") or []),
        )
    db.commit()
    db.refresh(row)
    return row


def fail_generation_run(db: Session, report_id: str, company_id: str, code: str) -> None:
    db.rollback()
    row = db.execute(
        select(Report).where(Report.id == report_id, Report.company_id == company_id)
    ).scalar_one_or_none()
    if row is None:
        return
    row.generation_status = "failed"
    row.generation_error_code = code[:80]
    row.report_json = {}
    db.commit()


def get_report_sources(db: Session, report_id: str, company_id: str) -> Optional[Dict[str, Any]]:
    report = get_report(db, report_id, company_id)
    if report is None:
        return None
    sources = list(
        db.execute(
            select(ReportSourceVersion)
            .where(
                ReportSourceVersion.report_id == report_id,
                ReportSourceVersion.company_id == company_id,
            )
            .order_by(ReportSourceVersion.position.asc())
        ).scalars()
    )
    evidence = list(
        db.execute(
            select(ReportEvidenceBinding)
            .where(
                ReportEvidenceBinding.report_id == report_id,
                ReportEvidenceBinding.company_id == company_id,
            )
            .order_by(ReportEvidenceBinding.retrieval_rank.asc())
        ).scalars()
    )
    return {
        "corpusMode": report.corpus_mode,
        "corpusSnapshotDigest": report.corpus_snapshot_digest,
        "retrievalEngineVersion": report.retrieval_engine_version,
        "orchestratorVersion": report.orchestrator_version,
        "executionMode": report.execution_mode or report.generation_mode,
        "llmProvider": report.llm_provider if report.llm_provider != "none" else None,
        "llmModel": report.llm_model,
        "sourceVersionCount": report.source_version_count,
        "evidenceSectionCount": report.evidence_section_count,
        "generationStatus": report.generation_status,
        "sourceVersions": [
            {
                "documentId": source.document_id,
                "documentVersionId": source.document_version_id,
                "versionNo": source.version_no,
                "manifestSha256": source.manifest_sha256,
                "finalizationTargetDigest": source.finalization_target_digest,
                "position": source.position,
            }
            for source in sources
        ],
        "evidenceBindings": [
            {
                "documentId": item.document_id,
                "documentVersionId": item.document_version_id,
                "documentTitle": item.document_title,
                "originalFilename": item.original_filename,
                "sectionOrdinal": item.section_ordinal,
                "headingPath": item.heading_path or [],
                "sectionTitle": item.section_title,
                "anchorId": item.anchor_id,
                "citationId": item.citation_id,
                "sectionSignature": item.section_signature,
                "retrievalRank": item.retrieval_rank,
                "retrievalScore": item.retrieval_score,
                "selectedForPrompt": item.selected_for_prompt,
                "citedInFinal": item.cited_in_final,
                "excerpt": item.evidence_excerpt,
            }
            for item in evidence
        ],
    }


def delete_report(db: Session, report_id: str, company_id: str) -> bool:
    row = get_report(db, report_id, company_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
