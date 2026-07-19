"""Declarative claim candidate production and deterministic gating."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.agents.section_provider import TenantCorpusProvider
from app.contracts import ClaimCandidate, ClaimDecision, ClaimSpec, SectionRef

from .gate import GATE_ENGINE_VERSION, REASON_MALFORMED, decide_claim
from .matchers import (
    MATCHER_ENGINE_VERSION,
    EvidenceContext,
    MatcherEvaluationBudget,
    MatcherObservation,
    evaluate_matcher,
)
from .patterns import ClaimPatternRelease, load_active_claim_patterns

MAX_LLM_PROPOSALS = 20
MAX_PROPOSAL_STATEMENT_CHARS = 1000


@dataclass(frozen=True)
class EvaluatedClaim:
    candidate: ClaimCandidate
    decision: ClaimDecision
    spec: ClaimSpec | None
    requirement_observations: Mapping[str, MatcherObservation]


@dataclass(frozen=True)
class ClaimRunResult:
    release: ClaimPatternRelease
    evaluated: tuple[EvaluatedClaim, ...]
    metrics: Mapping[str, Mapping[str, int]]

    @property
    def candidates(self) -> tuple[ClaimCandidate, ...]:
        return tuple(item.candidate for item in self.evaluated)

    @property
    def decisions(self) -> tuple[ClaimDecision, ...]:
        return tuple(item.decision for item in self.evaluated)

    @property
    def accepted(self) -> tuple[EvaluatedClaim, ...]:
        return tuple(item for item in self.evaluated if item.decision.decision == "accepted")

    def telemetry(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "schemaVersion": self.release.schema_version,
            "claimPackId": self.release.claim_pack_id,
            "releaseVersion": self.release.release_version,
            "releaseDigest": self.release.release_digest,
            "matcherEngineVersion": MATCHER_ENGINE_VERSION,
            "gateEngineVersion": GATE_ENGINE_VERSION,
            "candidateCount": len(self.evaluated),
            "acceptedCount": sum(item.decision.decision == "accepted" for item in self.evaluated),
            "rejectedCount": sum(item.decision.decision == "rejected" for item in self.evaluated),
            "insufficientEvidenceCount": sum(item.decision.decision == "insufficient_evidence" for item in self.evaluated),
            "llmProposedCount": sum(item.candidate.candidate_source == "llm_proposal" for item in self.evaluated),
            "decisions": [
                {
                    "candidateId": item.candidate.candidate_id,
                    "claimSpecId": item.candidate.claim_spec_id,
                    "candidateSource": item.candidate.candidate_source,
                    "decision": item.decision.decision,
                    "supportScore": item.decision.support_score,
                    "threshold": item.decision.threshold,
                    "gatePolicyId": item.decision.gate_policy_id,
                    "gatePolicyVersion": item.decision.gate_policy_version,
                    "reasonCodes": list(item.decision.reason_codes),
                    "acceptedBindingIds": list(item.decision.accepted_binding_ids),
                }
                for item in self.evaluated
            ],
            "patternMetrics": {key: dict(value) for key, value in sorted(self.metrics.items())},
        }


@dataclass(frozen=True)
class AcceptedClaimProjection:
    """The sole analytical projection used while the claim engine is enabled."""

    workflow_steps: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    suggested_actions: list[dict[str, Any]]
    summary: str
    top_finding: str
    included_candidate_ids: set[str]


def _contexts(provider: TenantCorpusProvider) -> tuple[EvidenceContext, ...]:
    return tuple(
        EvidenceContext(
            binding_id=item.citation_id,
            citation_id=item.citation_id,
            document_id=item.document_id,
            version_id=item.document_version_id,
            anchor_id=item.anchor_id,
            text=item.text,
            heading=" / ".join([*item.heading_path, item.section_title]),
            category=item.category,
            topics=item.topics,
        )
        for item in provider.evidence
    )


def _candidate_id(
    *, spec_id: str, pattern_version: str, snapshot: str, source: str, bindings: Sequence[str], ordinal: int
) -> str:
    payload = {
        "spec": spec_id,
        "version": pattern_version,
        "snapshot": snapshot,
        "source": source,
        "bindings": sorted(set(bindings)),
        "ordinal": ordinal,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _observations(spec: ClaimSpec, evidence: Sequence[EvidenceContext]) -> tuple[MatcherObservation, dict[str, MatcherObservation]]:
    budget = MatcherEvaluationBudget()
    root = evaluate_matcher(spec.matcher, evidence, budget=budget)
    requirements = {
        str(need["id"]): evaluate_matcher(need["matcher"], evidence, budget=budget)
        for need in spec.evidence_needs
    }
    return root, requirements


def _candidate(
    spec: ClaimSpec,
    provider: TenantCorpusProvider,
    root: MatcherObservation,
    requirements: Mapping[str, MatcherObservation],
    *,
    source: str,
    statement: str,
    binding_ids: Sequence[str],
    proposer: Mapping[str, str] | None,
    ordinal: int,
) -> ClaimCandidate:
    evidence_by_citation = {item.citation_id: item for item in provider.evidence}
    valid_refs = tuple(
        SectionRef(item.document_id, item.document_version_id, item.anchor_id)
        for citation in sorted(set(binding_ids))
        if (item := evidence_by_citation.get(citation)) is not None
    )
    audit = [
        {"requirementId": need_id, "purpose": next(
            str(need.get("purpose", "support")) for need in spec.evidence_needs if need["id"] == need_id
        ), **observation.audit_dict()}
        for need_id, observation in sorted(requirements.items())
    ]
    return ClaimCandidate(
        spec_ref=f"{spec.id}@{spec.version}" if source == "deterministic_pattern" else None,
        proposer_ref=proposer if source == "llm_proposal" else None,
        candidate_sections=valid_refs,
        proposed_severity=spec.priority_hint,
        candidate_id=_candidate_id(
            spec_id=spec.id,
            pattern_version=spec.version,
            snapshot=provider.snapshot_digest,
            source=source,
            bindings=binding_ids,
            ordinal=ordinal,
        ),
        claim_spec_id=spec.id,
        pattern_version=spec.version,
        proposed_statement=statement[:MAX_PROPOSAL_STATEMENT_CHARS],
        source_snapshot_id=provider.snapshot_digest,
        source_snapshot_digest=provider.snapshot_digest,
        proposed_binding_ids=tuple(sorted(set(str(value) for value in binding_ids))),
        matcher_observations=tuple(audit),
        deterministic_features={"rootMatcherMatched": 1.0 if root.matched else 0.0},
        proposer_metadata=proposer,
        candidate_source=source,
    )


def _malformed_llm_candidate(provider: TenantCorpusProvider, proposal: Mapping[str, Any], ordinal: int) -> EvaluatedClaim:
    spec_id = str(proposal.get("claimSpecId") or "unknown")[:160]
    bindings = tuple(str(value)[:120] for value in proposal.get("evidenceCodes", []) if isinstance(value, str))
    candidate = ClaimCandidate(
        proposer_ref={"kind": "llm", "model": str(proposal.get("model") or "unknown")[:80], "promptVersion": str(proposal.get("promptVersion") or "unknown")[:80]},
        candidate_id=_candidate_id(spec_id=spec_id, pattern_version="unknown", snapshot=provider.snapshot_digest, source="llm_proposal", bindings=bindings, ordinal=ordinal),
        claim_spec_id=spec_id,
        pattern_version="unknown",
        proposed_statement=str(proposal.get("statement") or "")[:MAX_PROPOSAL_STATEMENT_CHARS],
        source_snapshot_id=provider.snapshot_digest,
        source_snapshot_digest=provider.snapshot_digest,
        proposed_binding_ids=bindings,
        candidate_source="llm_proposal",
    )
    decision = ClaimDecision(
        candidate.candidate_id, "rejected", 0.0, 1.0, (REASON_MALFORMED,), (), (), (), (),
        "unknown", "unknown", GATE_ENGINE_VERSION, {"requirementCoverage": 0.0},
    )
    return EvaluatedClaim(candidate, decision, None, {})


def run_claim_engine(
    provider: TenantCorpusProvider,
    *,
    llm_proposals: Sequence[Mapping[str, Any]] = (),
    release: ClaimPatternRelease | None = None,
) -> ClaimRunResult:
    release = release or load_active_claim_patterns()
    evidence = _contexts(provider)
    allowed = {item.binding_id for item in evidence}
    binding_documents = {item.binding_id: item.document_id for item in evidence}
    evaluated: list[EvaluatedClaim] = []
    metric_rows: dict[str, dict[str, int]] = {}

    for ordinal, spec in enumerate(release.specs):
        if not spec.enabled:
            continue
        root, requirements = _observations(spec, evidence)
        support_bindings = {
            binding
            for need in spec.evidence_needs
            if need.get("purpose", "support") == "support"
            for binding in requirements[str(need["id"])].binding_ids
        }
        statement = str(spec.output_metadata.get("statement") or spec.title)
        candidate = _candidate(
            spec, provider, root, requirements, source="deterministic_pattern", statement=statement,
            binding_ids=tuple(sorted(support_bindings)), proposer=None, ordinal=ordinal,
        )
        decision = decide_claim(
            candidate, spec, release.policies[spec.gate_policy_id], requirements,
            allowed_binding_ids=allowed, binding_documents=binding_documents,
        )
        evaluated.append(EvaluatedClaim(candidate, decision, spec, requirements))
        metric_rows[spec.id] = {
            "evaluatedCount": 1,
            "firedCount": int(root.matched),
            "candidateCount": 1,
            "bindingCount": len(candidate.proposed_binding_ids),
            "acceptedCount": int(decision.decision == "accepted"),
            "rejectedCount": int(decision.decision == "rejected"),
            "insufficientEvidenceCount": int(decision.decision == "insufficient_evidence"),
            "finalReportInclusionCount": 0,
            "llmProposedCount": 0,
        }

    specs = {spec.id: spec for spec in release.specs if spec.enabled}
    for offset, proposal in enumerate(tuple(llm_proposals)[:MAX_LLM_PROPOSALS], start=len(release.specs)):
        spec = specs.get(str(proposal.get("claimSpecId") or ""))
        codes = proposal.get("evidenceCodes")
        statement = proposal.get("statement")
        if spec is None or not isinstance(codes, list) or not isinstance(statement, str) or not statement.strip() or len(statement) > MAX_PROPOSAL_STATEMENT_CHARS:
            evaluated.append(_malformed_llm_candidate(provider, proposal, offset))
            continue
        # Citation codes are non-authoritative hints. Every proposal is matched
        # against the same complete frozen M4 evidence set as its deterministic
        # candidate, so selective citation cannot hide conflicts or create
        # support.
        root, requirements = _observations(spec, evidence)
        proposer = {
            "kind": "llm",
            "model": str(proposal.get("model") or "unknown")[:80],
            "promptVersion": str(proposal.get("promptVersion") or "unknown")[:80],
        }
        candidate = _candidate(
            spec, provider, root, requirements, source="llm_proposal", statement=statement.strip(),
            binding_ids=tuple(str(value) for value in codes if isinstance(value, str)), proposer=proposer, ordinal=offset,
        )
        decision = decide_claim(
            candidate, spec, release.policies[spec.gate_policy_id], requirements,
            allowed_binding_ids=allowed, binding_documents=binding_documents,
        )
        evaluated.append(EvaluatedClaim(candidate, decision, spec, requirements))
        row = metric_rows[spec.id]
        row["candidateCount"] += 1
        row["bindingCount"] += len(candidate.proposed_binding_ids)
        row["acceptedCount"] += int(decision.decision == "accepted")
        row["rejectedCount"] += int(decision.decision == "rejected")
        row["insufficientEvidenceCount"] += int(decision.decision == "insufficient_evidence")
        row["llmProposedCount"] += 1

    return ClaimRunResult(release, tuple(evaluated), metric_rows)


def _selected_accepted_claims(result: ClaimRunResult) -> tuple[EvaluatedClaim, ...]:
    selected: dict[str, EvaluatedClaim] = {}
    for item in result.accepted:
        if item.spec is None:
            continue
        existing = selected.get(item.spec.id)
        # Higher deterministic support wins. On an exact score tie, an accepted
        # LLM proposal may supply wording to the existing narrative gate; it
        # still has no authority over acceptance or citations.
        key = (
            -item.decision.support_score,
            item.candidate.candidate_source != "llm_proposal",
            item.candidate.candidate_id,
        )
        if existing is None:
            selected[item.spec.id] = item
        else:
            old_key = (
                -existing.decision.support_score,
                existing.candidate.candidate_source != "llm_proposal",
                existing.candidate.candidate_id,
            )
            if key < old_key:
                selected[item.spec.id] = item
    return tuple(item for _spec_id, item in sorted(selected.items()))


def project_accepted_claims(
    result: ClaimRunResult,
    *,
    persona_title: str,
    market: str,
    document_count: int,
) -> AcceptedClaimProjection:
    """Project analytical output from accepted decisions, never raw sections."""
    risks: list[dict[str, Any]] = []
    workflow: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    included: set[str] = set()
    for item in _selected_accepted_claims(result):
        if item.spec is None or not item.decision.accepted_binding_ids:
            continue
        output = item.spec.output_metadata
        citation = item.decision.accepted_binding_ids[0]
        title = output.get("title", item.spec.title)
        statement = (
            item.candidate.proposed_statement
            if item.candidate.candidate_source == "llm_proposal"
            else output.get("description", item.candidate.proposed_statement)
        )
        recommended_fix = output.get(
            "recommendedFix", "Review the accepted claim and its cited evidence."
        )
        impact = output.get("businessImpact", "The accepted finding requires review.")
        owner = output.get("owner", "Unassigned")
        kind = output.get("kind")
        if kind in {"risk", "finding"} and len(risks) < 6:
            risks.append({
                "severity": output.get("severity", item.spec.priority_hint or "Medium"),
                "title": title,
                "description": statement,
                "businessImpact": impact,
                "evidenceCode": citation,
                "recommendedFix": recommended_fix,
                "owner": owner,
            })
        if kind in {"risk", "finding", "workflow"} and len(workflow) < 6:
            workflow.append({
                "step": len(workflow) + 1,
                "title": title if kind == "workflow" else f"Address {title}",
                "description": statement,
                "whyItMatters": impact,
                "expectedOutput": recommended_fix,
                "evidenceCode": citation,
            })
        if kind in {"risk", "finding", "recommendation"} and len(actions) < 6:
            actions.append({"title": recommended_fix, "detail": f"Owner: {owner}. Evidence: {citation}."})
        included.add(item.candidate.candidate_id)

    if not included:
        summary = (
            f"The available frozen evidence did not support any accepted claim for "
            f"{persona_title} in {market}. No workflow, risks, or recommendations were "
            "produced; rejected and insufficient candidates remain audit-only."
        )
        top_finding = "No accepted claim was supported by the available frozen evidence."
    else:
        top = risks[0] if risks else None
        top_title = top["title"] if top else "the accepted claim set"
        top_code = top["evidenceCode"] if top else next(
            item.decision.accepted_binding_ids[0]
            for item in _selected_accepted_claims(result)
            if item.candidate.candidate_id in included
        )
        summary = (
            f"For {persona_title} in {market}, Evidentia evaluated {document_count} frozen "
            f"source document{'s' if document_count != 1 else ''} and accepted {len(included)} "
            f"grounded claim{'s' if len(included) != 1 else ''}. The leading accepted finding "
            f"is {top_title}, supported by {top_code}. Workflow and recommendations are limited "
            "to these accepted claims."
        )
        top_finding = f"The leading accepted finding is {top_title}, supported by {top_code}."
    return AcceptedClaimProjection(workflow, risks, actions, summary, top_finding, included)


def accepted_claim_risks(result: ClaimRunResult) -> tuple[list[dict[str, Any]], set[str]]:
    """Compatibility helper for focused callers; orchestration uses the full projection."""
    projection = project_accepted_claims(
        result, persona_title="the selected persona", market="the selected market", document_count=0
    )
    return projection.risks, projection.included_candidate_ids
