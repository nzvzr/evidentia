"""Versioned deterministic evidence-support gate (the sole claim authority)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Sequence

from app.contracts import ClaimCandidate, ClaimDecision, ClaimSpec

from .matchers import MatcherObservation, flatten_observations
from .patterns import GatePolicy

GATE_ENGINE_VERSION = "deterministic-support-gate-v1"

REASON_ACCEPTED = "SUPPORT_THRESHOLD_MET"
REASON_CONTRADICTED = "CONTRADICTING_EVIDENCE"
REASON_NO_EVIDENCE = "NO_VALID_EVIDENCE"
REASON_FOREIGN_EVIDENCE = "EVIDENCE_OUTSIDE_FROZEN_REGISTRY"
REASON_MISSING_REQUIRED = "MISSING_REQUIRED_MATCHER"
REASON_BELOW_REJECT = "SUPPORT_BELOW_REJECT_THRESHOLD"
REASON_BELOW_ACCEPT = "SUPPORT_BELOW_ACCEPT_THRESHOLD"
REASON_MALFORMED = "MALFORMED_CANDIDATE"


def _rounded(value: Decimal | float) -> float:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    bounded = min(Decimal("1"), max(Decimal("0"), decimal_value))
    return float(bounded.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def decide_claim(
    candidate: ClaimCandidate,
    spec: ClaimSpec,
    policy: GatePolicy,
    requirement_observations: Mapping[str, MatcherObservation],
    *,
    allowed_binding_ids: set[str],
    binding_documents: Mapping[str, str],
) -> ClaimDecision:
    """Fail-closed scoring over exact frozen binding ids and matcher audits."""
    proposed = tuple(sorted(set(candidate.proposed_binding_ids)))
    foreign = tuple(binding for binding in proposed if binding not in allowed_binding_ids)
    if not candidate.candidate_id or candidate.claim_spec_id != spec.id or foreign:
        reasons = (REASON_FOREIGN_EVIDENCE,) if foreign else (REASON_MALFORMED,)
        return ClaimDecision(
            candidate.candidate_id or "malformed",
            "rejected",
            0.0,
            float(policy.accept_threshold),
            reasons,
            (),
            tuple(str(need["id"]) for need in spec.evidence_needs if need.get("required")),
            foreign,
            (),
            policy.policy_id,
            policy.version,
            GATE_ENGINE_VERSION,
            {"requirementCoverage": 0.0},
        )

    support_needs = [need for need in spec.evidence_needs if need.get("purpose", "support") == "support"]
    conflict_needs = [need for need in spec.evidence_needs if need.get("purpose") == "conflict"]
    matched = tuple(sorted(
        str(need["id"]) for need in support_needs if requirement_observations[str(need["id"])].matched
    ))
    missing = tuple(sorted(
        str(need["id"]) for need in support_needs
        if need.get("required") and not requirement_observations[str(need["id"])].matched
    ))
    conflicts = tuple(sorted(
        binding
        for need in conflict_needs
        if requirement_observations[str(need["id"])].matched
        for binding in requirement_observations[str(need["id"])].binding_ids
    ))

    total_weight = sum(Decimal(str(need["weight"])) for need in support_needs) or Decimal("1")
    matched_weight = sum(
        Decimal(str(need["weight"]))
        for need in support_needs
        if requirement_observations[str(need["id"])].matched
    )
    coverage = matched_weight / total_weight
    all_nodes = [
        observation
        for need in support_needs
        for observation in flatten_observations(requirement_observations[str(need["id"])])
    ]
    leaf_nodes = [observation for observation in all_nodes if not observation.children]
    matcher_support = (
        Decimal(sum(1 for observation in leaf_nodes if observation.matched)) / Decimal(len(leaf_nodes))
        if leaf_nodes else Decimal("0")
    )
    attributed_support = {
        binding
        for need in support_needs
        if requirement_observations[str(need["id"])].matched
        for binding in requirement_observations[str(need["id"])].binding_ids
        if binding in allowed_binding_ids
    }
    # Proposed citations are hints only. They may narrow which matcher-attributed
    # support is attached to an LLM candidate, but can never create or increase
    # support. Deterministic candidates use the identical intersection semantics.
    valid_bindings = tuple(sorted(attributed_support.intersection(proposed)))
    binding_count = min(Decimal("1"), Decimal(len(valid_bindings)) / Decimal("2"))
    source_count = len({binding_documents[binding] for binding in valid_bindings})
    source_diversity = min(Decimal("1"), Decimal(source_count) / Decimal("2"))
    obligation = Decimal("1") if any(
        observation.primitive in {"obligation_term", "prohibition_term"} and observation.matched
        for observation in leaf_nodes
    ) else Decimal("0")
    weights = policy.weights
    positive_weight = (
        weights["requirementCoverage"] + weights["matcherSupport"] + weights["bindingCount"]
        + weights["sourceDiversity"] + weights["obligation"]
    ) or Decimal("1")
    raw = (
        coverage * weights["requirementCoverage"]
        + matcher_support * weights["matcherSupport"]
        + binding_count * weights["bindingCount"]
        + source_diversity * weights["sourceDiversity"]
        + obligation * weights["obligation"]
    ) / positive_weight
    if conflicts:
        raw -= weights["contradictionPenalty"]
    score = _rounded(raw)
    features = {
        "requirementCoverage": _rounded(coverage),
        "matcherSupport": _rounded(matcher_support),
        "bindingCount": float(len(valid_bindings)),
        "sourceCount": float(source_count),
        "sourceDiversity": _rounded(source_diversity),
        "obligationLanguage": float(obligation),
        "conflictCount": float(len(conflicts)),
    }

    if conflicts:
        decision, reasons, accepted = "rejected", (REASON_CONTRADICTED,), ()
    elif not valid_bindings:
        decision, reasons, accepted = "insufficient_evidence", (REASON_NO_EVIDENCE,), ()
    elif missing:
        decision, reasons, accepted = "insufficient_evidence", (REASON_MISSING_REQUIRED,), ()
    elif Decimal(str(score)) >= policy.accept_threshold:
        decision, reasons, accepted = "accepted", (REASON_ACCEPTED,), valid_bindings
    elif Decimal(str(score)) <= policy.reject_below:
        decision, reasons, accepted = "rejected", (REASON_BELOW_REJECT,), ()
    else:
        decision, reasons, accepted = "insufficient_evidence", (REASON_BELOW_ACCEPT,), ()

    return ClaimDecision(
        candidate.candidate_id,
        decision,
        score,
        float(policy.accept_threshold),
        reasons,
        matched,
        missing,
        tuple(sorted(set(conflicts))),
        accepted,
        policy.policy_id,
        policy.version,
        GATE_ENGINE_VERSION,
        features,
    )
