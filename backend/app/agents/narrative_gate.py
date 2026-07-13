"""Field-level narrative quality gate.

The LLM polish proposes new values for the summary, persona-brief description,
and suggested actions. Each candidate field is accepted only if it is strictly
better on its field-level narrative score AND does not regress factual
consistency or grounding AND does not add hallucination/injection warnings.
On ties the deterministic field is preserved (avoids needless rewriting).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from app.eval.metrics import (
    _tokens,
    action_alignment,
    action_usefulness,
    citation_accuracy,
    citation_coverage,
    concision,
    grounding_score,
    hallucination_warnings,
    narrative_score,
    persona_market_relevance,
    summary_completeness,
    summary_factual_consistency,
    validate_schema,
)
from app.tools.text_quality import VAGUE_PHRASES, is_precise_text


# --------------------------------------------------------------------------- #
# field-level scores
# --------------------------------------------------------------------------- #

def summary_field_score(report: Dict[str, Any], available: Set[str], expected: Optional[Dict] = None) -> float:
    fc = summary_factual_consistency(report, available, expected)
    comp = summary_completeness(report, expected)
    con = concision(report)
    return round(100 * (0.4 * fc + 0.4 * comp + 0.2 * con), 2)


def description_field_score(report: Dict[str, Any]) -> float:
    brief = report.get("personaBrief", {}) or {}
    desc = brief.get("description", "") or ""
    if not desc.strip():
        return 0.0
    low = desc.lower()
    persona = report.get("persona", "")
    priorities = " ".join(brief.get("priorities", []) + brief.get("relevantTopics", []))
    checks = [
        any(t in low for t in _tokens(persona)) if _tokens(persona) else False,
        any(t in low for t in _tokens(priorities)) if _tokens(priorities) else True,
    ]
    relevance = sum(1 for c in checks if c) / len(checks)
    precise = 1.0 if is_precise_text(desc, max_len=500) else 0.0
    vague = 1 if any(p in low for p in VAGUE_PHRASES) else 0
    return round(max(0.0, 100 * (0.5 * relevance + 0.5 * precise) - 15 * vague), 2)


def actions_field_score(report: Dict[str, Any], expected: Optional[Dict] = None) -> float:
    au = action_usefulness(report)
    aa = action_alignment(report, expected)
    text = " ".join(
        f"{a.get('title', '')} {a.get('detail') or a.get('description') or ''}"
        for a in report.get("suggestedActions", [])
    ).lower()
    vague = 1 if any(p in text for p in VAGUE_PHRASES) else 0
    return round(max(0.0, 100 * (0.6 * au + 0.4 * aa) - 15 * vague), 2)


def _grounding(report: Dict[str, Any], available: Set[str], custom: str) -> float:
    schema_ok, _ = validate_schema(report)
    return grounding_score(
        schema_ok,
        citation_accuracy(report, available),
        citation_coverage(report, available),
        hallucination_warnings(report, available, custom)[0],
    )


def _decide(det_r, cand_r, available, custom, score_fn, check_factual):
    det_s = score_fn(det_r)
    cand_s = score_fn(cand_r)
    if cand_s < det_s:
        return False, "narrative-regression", det_s, cand_s
    if cand_s == det_s:
        return False, "no-improvement", det_s, cand_s
    if hallucination_warnings(cand_r, available, custom)[0] > hallucination_warnings(det_r, available, custom)[0]:
        return False, "warnings-increased", det_s, cand_s
    if _grounding(cand_r, available, custom) < _grounding(det_r, available, custom):
        return False, "grounding-decreased", det_s, cand_s
    if check_factual and summary_factual_consistency(cand_r, available) < summary_factual_consistency(det_r, available):
        return False, "factual-regression", det_s, cand_s
    return True, "accepted", det_s, cand_s


def gate_fields(
    report: Dict[str, Any],
    updates: Dict[str, Any],
    available: Set[str],
    custom_persona: str = "",
    expected: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Apply accepted candidate fields to `report` in place; return gate summary."""
    det_narrative = narrative_score(report, available, custom_persona, expected)

    # Candidate report with all proposed updates applied (for candidate score).
    cand_all = dict(report)
    if "summary" in updates:
        cand_all["summary"] = updates["summary"]
    if "personaBriefDescription" in updates:
        cand_all["personaBrief"] = {**report["personaBrief"], "description": updates["personaBriefDescription"]}
    if "suggestedActions" in updates:
        cand_all["suggestedActions"] = updates["suggestedActions"]
    candidate_narrative = narrative_score(cand_all, available, custom_persona, expected)

    accepted: List[str] = []
    rejected: List[str] = []
    reasons: Dict[str, str] = {}

    def run(field_key: str, present: bool, build_cand, apply, score_fn, check_factual: bool):
        if not present:
            return
        cand_r = build_cand()
        ok, reason, _ds, _cs = _decide(report, cand_r, available, custom_persona, score_fn, check_factual)
        if ok:
            apply()
            accepted.append(field_key)
        else:
            rejected.append(field_key)
            reasons[field_key] = reason

    run(
        "summary", "summary" in updates,
        build_cand=lambda: {**report, "summary": updates.get("summary")},
        apply=lambda: report.__setitem__("summary", updates.get("summary")),
        score_fn=lambda r: summary_field_score(r, available, expected),
        check_factual=True,
    )
    run(
        "personaBrief.description", "personaBriefDescription" in updates,
        build_cand=lambda: {**report, "personaBrief": {**report["personaBrief"], "description": updates.get("personaBriefDescription")}},
        apply=lambda: report["personaBrief"].__setitem__("description", updates.get("personaBriefDescription")),
        score_fn=description_field_score,
        check_factual=False,
    )
    run(
        "suggestedActions", "suggestedActions" in updates,
        build_cand=lambda: {**report, "suggestedActions": updates.get("suggestedActions")},
        apply=lambda: report.__setitem__("suggestedActions", updates.get("suggestedActions")),
        score_fn=lambda r: actions_field_score(r, expected),
        check_factual=False,
    )

    final_narrative = narrative_score(report, available, custom_persona, expected)

    if accepted and not rejected:
        decision = "all-accepted"
    elif rejected and not accepted:
        decision = "all-rejected"
    elif accepted and rejected:
        decision = "partial"
    else:
        decision = "no-updates"

    return {
        "acceptedFields": accepted,
        "rejectedFields": rejected,
        "rejectionReasons": reasons,
        "deterministicNarrativeScore": det_narrative,
        "candidateNarrativeScore": candidate_narrative,
        "finalNarrativeScore": final_narrative,
        "narrativeGateDecision": decision,
    }
