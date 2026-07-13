"""Auto intensity router (calibrated, conservative, deterministic).

Selects off / summary / full from *pre-LLM deterministic* signals only. Calibrated
from the verified v1 benchmark (full mode is structurally safe after gating but on
average worse than summary at ~4x cost / ~5x latency), so:

- summary is the default (cheap narrative polish that reliably helps);
- off is chosen only when the deterministic baseline is already strong;
- full is chosen only when there is BOTH a clear deterministic analytical weakness
  AND sufficient selected-document evidence to support structural refinement, and
  multiple independent analytical-opportunity signals agree, and the predicted
  incremental gain clears a configurable threshold.

Custom persona alone, a single contradiction, a large corpus, or a slightly-low
confidence never force full. Pure and deterministic for easy unit testing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

# --- off eligibility (deterministic baseline already strong) ---
CONF_HIGH = 92
COVERAGE_HIGH = 90.0
NARRATIVE_STRONG = 90.0

# --- analytical-opportunity thresholds (a "weak" deterministic baseline) ---
STRUCT_WEAK = 60.0            # deterministic structural score below this is weak
NARRATIVE_WEAK = 85.0         # deterministic narrative score below this is weak
CONF_WEAK = 80               # deterministic confidence below this is weak
CONTRADICTIONS_STRONG = 2    # a single contradiction is not enough
DROPPED_RISKS_STRONG = 3     # many supportable risks the baseline under-selected

# --- evidence sufficiency for structural refinement ---
MIN_DOCS_FOR_FULL = 3
MIN_GROUNDED_RISKS = 2
MIN_GROUNDED_STEPS = 2
MAX_INSUFFICIENT_ITEMS = 1
MIN_EVIDENCE_SUPPORT_AVG = 6.0

# full is eligible only when >= this many opportunity signals agree
MIN_OPPORTUNITY_SIGNALS = 2
# default minimum predicted incremental gain (overall points) to pick full
FULL_GAIN_THRESHOLD = 0.2


@dataclass
class RoutingSignals:
    # deterministic analytical quality (computed from the baseline, pre-LLM)
    deterministic_structural_score: float = 0.0
    deterministic_narrative_score: float = 0.0
    # corpus / request shape
    document_complexity: int = 0
    contradictions: int = 0
    persona_complexity: int = 0
    deterministic_confidence: int = 0
    citation_coverage: float = 0.0
    # source-constrained generation telemetry
    grounded_risks_kept: int = 0
    grounded_workflow_steps_kept: int = 0
    unsupported_risks_dropped: int = 0
    insufficient_evidence_items: int = 0
    source_document_mismatch: int = 0
    evidence_support_score_avg: float = 0.0
    evidence_support_score_min: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "deterministicStructuralScore": self.deterministic_structural_score,
            "deterministicNarrativeScore": self.deterministic_narrative_score,
            "documentComplexity": self.document_complexity,
            "contradictions": self.contradictions,
            "personaComplexity": self.persona_complexity,
            "deterministicConfidence": self.deterministic_confidence,
            "citationCoverage": self.citation_coverage,
            "groundedRisksKept": self.grounded_risks_kept,
            "groundedWorkflowStepsKept": self.grounded_workflow_steps_kept,
            "unsupportedRisksDropped": self.unsupported_risks_dropped,
            "insufficientEvidenceItemsFinal": self.insufficient_evidence_items,
            "sourceDocumentMismatchCount": self.source_document_mismatch,
            "evidenceSupportScoreAvg": self.evidence_support_score_avg,
            "evidenceSupportScoreMin": self.evidence_support_score_min,
        }


@dataclass
class RoutingDecision:
    mode: str
    reason: str
    confidence: float
    predicted_incremental_gain: float
    alternative_mode: str
    full_eligibility: Dict[str, bool] = field(default_factory=dict)
    signals: Dict[str, Any] = field(default_factory=dict)

    def as_telemetry(self) -> Dict[str, Any]:
        return {
            "routingReason": self.reason,
            "routingSignals": self.signals,
            "routingConfidence": round(self.confidence, 3),
            "predictedIncrementalGain": round(self.predicted_incremental_gain, 3),
            "selectedMode": self.mode,
            "alternativeMode": self.alternative_mode,
            "fullEligibilityChecks": self.full_eligibility,
        }


def _opportunity_signals(s: RoutingSignals) -> Dict[str, bool]:
    return {
        "weakStructural": s.deterministic_structural_score < STRUCT_WEAK,
        "weakNarrative": s.deterministic_narrative_score < NARRATIVE_WEAK,
        "lowConfidence": s.deterministic_confidence < CONF_WEAK,
        "multipleContradictions": s.contradictions >= CONTRADICTIONS_STRONG,
        "manyDroppedRisks": s.unsupported_risks_dropped >= DROPPED_RISKS_STRONG,
    }


def _evidence_checks(s: RoutingSignals) -> Dict[str, bool]:
    return {
        "enoughDocuments": s.document_complexity >= MIN_DOCS_FOR_FULL,
        "enoughGroundedRisks": s.grounded_risks_kept >= MIN_GROUNDED_RISKS,
        "enoughGroundedSteps": s.grounded_workflow_steps_kept >= MIN_GROUNDED_STEPS,
        "noSourceMismatch": s.source_document_mismatch == 0,
        "lowInsufficientEvidence": s.insufficient_evidence_items <= MAX_INSUFFICIENT_ITEMS,
        "sufficientEvidenceSupport": s.evidence_support_score_avg >= MIN_EVIDENCE_SUPPORT_AVG,
    }


def _predict_gain(opportunity_count: int, evidence_ok: bool, weakness: bool) -> float:
    if not (evidence_ok and weakness):
        return 0.0
    # conservative heuristic: each independent opportunity signal is worth ~0.15
    # overall points of expected full-over-summary gain.
    return round(0.15 * opportunity_count, 3)


def route_intensity(signals: RoutingSignals, full_gain_threshold: float = FULL_GAIN_THRESHOLD) -> RoutingDecision:
    opp = _opportunity_signals(signals)
    ev = _evidence_checks(signals)
    opportunity_count = sum(1 for v in opp.values() if v)
    weakness = opp["weakStructural"] or opp["weakNarrative"] or opp["lowConfidence"]
    evidence_ok = all(ev.values())

    insufficient_evidence = (
        signals.document_complexity <= 1
        or (signals.grounded_risks_kept + signals.grounded_workflow_steps_kept) < 2
    )
    predicted_gain = _predict_gain(opportunity_count, evidence_ok, weakness)

    eligibility = {
        **{f"opp:{k}": v for k, v in opp.items()},
        **{f"evidence:{k}": v for k, v in ev.items()},
        "analyticalWeakness": weakness,
        "evidenceSufficient": evidence_ok,
        "enoughOpportunitySignals": opportunity_count >= MIN_OPPORTUNITY_SIGNALS,
        "notInsufficientEvidence": not insufficient_evidence,
        "predictedGainClearsThreshold": predicted_gain > full_gain_threshold,
    }

    full_eligible = (
        weakness
        and evidence_ok
        and not insufficient_evidence
        and opportunity_count >= MIN_OPPORTUNITY_SIGNALS
        and predicted_gain > full_gain_threshold
    )

    if full_eligible:
        return RoutingDecision(
            mode="full", alternative_mode="summary",
            reason=f"analytical-weakness + sufficient-evidence + {opportunity_count} opportunity signals",
            confidence=min(0.9, 0.5 + 0.1 * opportunity_count),
            predicted_incremental_gain=predicted_gain,
            full_eligibility=eligibility, signals=signals.as_dict(),
        )

    # Not full → prefer the cheaper mode. off only when the baseline is already
    # strong; otherwise summary (reliable, cheap narrative polish).
    high_conf_simple = (
        signals.deterministic_confidence >= CONF_HIGH
        and signals.citation_coverage >= COVERAGE_HIGH
        and signals.contradictions == 0
        and signals.persona_complexity == 0
        and signals.deterministic_narrative_score >= NARRATIVE_STRONG
    )
    if high_conf_simple:
        return RoutingDecision(
            mode="off", alternative_mode="summary",
            reason="high-confidence simple baseline; deterministic is sufficient",
            confidence=0.8, predicted_incremental_gain=0.0,
            full_eligibility=eligibility, signals=signals.as_dict(),
        )

    reason = "insufficient evidence for full; summary polish" if insufficient_evidence else (
        "no clear full opportunity; default summary polish"
    )
    return RoutingDecision(
        mode="summary", alternative_mode="off",
        reason=reason, confidence=0.7, predicted_incremental_gain=predicted_gain,
        full_eligibility=eligibility, signals=signals.as_dict(),
    )


def default_routing_decision(mode: str, configured: str) -> RoutingDecision:
    """Telemetry for non-auto (explicitly configured) runs."""
    return RoutingDecision(
        mode=mode, alternative_mode=mode,
        reason=f"configured:{configured}", confidence=1.0,
        predicted_incremental_gain=0.0, full_eligibility={}, signals={},
    )
