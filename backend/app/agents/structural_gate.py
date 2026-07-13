"""Structural quality gate for Evidentia full LLM mode.

Full mode used to overwrite the deterministic persona brief, workflow steps and
risks outright. This module keeps the deterministic *analytical* baseline intact,
scores an LLM candidate with deterministic structural scorers, reconciles
workflow/risk items one by one, and accepts a candidate component only when it is
strictly better AND does not regress grounding, citation accuracy, warnings,
source-document ownership, insufficient-evidence count, or schema validity.

Everything here is deterministic (no LLM, no embeddings) and unit-testable.
`compose_fn(personaBrief, workflowSteps, risks) -> report` is injected so the
gate can build shadow reports without importing the orchestrator (avoids cycles).
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Callable, Dict, List, Set, Tuple

from app.eval.metrics import (
    DOMAIN_TERMS,
    citation_accuracy,
    citation_coverage,
    grounding_score,
    hallucination_warnings,
    validate_schema,
)
from app.tools.citation_tools import INSUFFICIENT_EVIDENCE
from app.tools.evidence_support import tokens as ev_tokens
from app.tools.text_quality import VAGUE_PHRASES, is_precise_text

Report = Dict[str, Any]
Item = Dict[str, Any]

_OPERATIONAL_VERBS = {
    "verify", "confirm", "draft", "escalate", "attach", "enable", "define", "replace",
    "map", "design", "document", "review", "open", "export", "schedule", "flag",
    "generate", "validate", "list", "model", "refresh", "set", "prepare", "identify",
    "check", "triage", "route", "resolve", "provision", "add", "publish", "reconcile",
    "assess", "build", "create", "run", "update", "remediate", "mitigate", "audit",
    "align", "complete", "study", "bookmark", "meet", "close", "circulate", "pull",
}
_CONTRADICTION_TERMS = {
    "conflict", "contradict", "inconsistent", "deprecated", "undefined", "silent",
    "omits", "missing", "unsupported", "ambiguous", "untested", "gap",
}
_MIN_SUPPORT_OVERLAP = 2
_DUP_JACCARD = 0.6


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #

def _by_code(sections: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {s["citationId"]: s for s in sections}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _supported(text: str, section: Dict[str, Any] | None) -> Tuple[bool, List[str]]:
    if not section:
        return False, []
    overlap = ev_tokens(text) & ev_tokens(f"{section['sectionTitle']} {section['excerpt']}")
    return len(overlap) >= _MIN_SUPPORT_OVERLAP, sorted(overlap)


def _specificity(text: str, max_len: int) -> float:
    if not text.strip():
        return 0.0
    low = text.lower()
    precise = 1.0 if is_precise_text(text, max_len=max_len) else 0.0
    domain = 1.0 if (ev_tokens(text) & DOMAIN_TERMS) else 0.0
    vague = 1.0 if any(p in low for p in VAGUE_PHRASES) else 0.0
    return max(0.0, 0.5 * precise + 0.5 * domain - 0.3 * vague)


def _is_valid_code(code: str, available: Set[str]) -> bool:
    return bool(code) and code != INSUFFICIENT_EVIDENCE and code in available


def _persona_focus_tokens(persona_brief: Dict[str, Any]) -> Set[str]:
    blob = " ".join(
        persona_brief.get("relevantTopics", [])
        + persona_brief.get("priorities", [])
        + persona_brief.get("riskFocus", [])
    )
    return ev_tokens(blob)


# --------------------------------------------------------------------------- #
# item-level structural scores (0..100)
# --------------------------------------------------------------------------- #

def risk_item_score(risk: Item, by_code: Dict[str, Dict[str, Any]], available: Set[str]) -> float:
    code = risk.get("evidenceCode", "")
    text = f"{risk.get('title', '')} {risk.get('description', '')}"
    valid = _is_valid_code(code, available)
    supported, _ = _supported(text, by_code.get(code))
    spec = _specificity(f"{text} {risk.get('businessImpact', '')} {risk.get('recommendedFix', '')}", 500)
    fields_ok = all(risk.get(k) for k in ("title", "description", "businessImpact", "recommendedFix", "owner"))
    sev_ok = risk.get("severity") in ("High", "Medium", "Low")
    score = (
        0.35 * (1.0 if valid else 0.0)
        + 0.30 * (1.0 if supported else 0.0)
        + 0.25 * spec
        + 0.10 * (1.0 if (fields_ok and sev_ok) else 0.0)
    )
    return round(100 * score, 2)


def workflow_item_score(step: Item, by_code: Dict[str, Dict[str, Any]], available: Set[str]) -> float:
    code = step.get("evidenceCode", "")
    text = f"{step.get('title', '')} {step.get('description', '')}"
    valid = _is_valid_code(code, available)
    supported, _ = _supported(text, by_code.get(code))
    title = step.get("title", "") or ""
    first = title.strip().split()[0].lower().strip(":,") if title.strip() else ""
    verb_ok = first in _OPERATIONAL_VERBS
    fields_ok = all(step.get(k) for k in ("title", "description", "whyItMatters", "expectedOutput"))
    spec = _specificity(text, 400)
    score = (
        0.30 * (1.0 if valid else 0.0)
        + 0.30 * (1.0 if supported else 0.0)
        + 0.20 * (1.0 if (verb_ok and fields_ok) else 0.0)
        + 0.20 * spec
    )
    return round(100 * score, 2)


# --------------------------------------------------------------------------- #
# component-level structural scores (0..100) + detail
# --------------------------------------------------------------------------- #

def persona_structural_score(
    persona_brief: Dict[str, Any], sections: List[Dict[str, Any]], market: str, persona_key: str
) -> Tuple[float, Dict[str, Any]]:
    desc = persona_brief.get("description", "") or ""
    text = " ".join([
        persona_brief.get("title", ""), desc,
        " ".join(persona_brief.get("relevantTopics", []) + persona_brief.get("riskFocus", [])),
    ]).lower()
    section_tokens: Set[str] = set()
    for s in sections:
        section_tokens |= ev_tokens(f"{s['sectionTitle']} {s['excerpt']}")

    persona_rel = 1.0 if (persona_key in text or ev_tokens(persona_key) & ev_tokens(text)) else 0.0
    market_tok = ev_tokens(market)
    market_rel = 1.0 if (not market_tok or (market_tok & ev_tokens(text))) else 0.0
    topic_tokens = _persona_focus_tokens(persona_brief)
    source_rel = 1.0 if (topic_tokens & section_tokens) else 0.0
    precise = 1.0 if is_precise_text(desc, max_len=500) else 0.0
    generic = 1.0 if any(p in desc.lower() for p in VAGUE_PHRASES) else 0.0
    precision = max(0.0, precise - generic)

    score = 100 * (0.30 * persona_rel + 0.20 * market_rel + 0.25 * source_rel + 0.25 * precision)
    detail = {
        "personaRelevance": persona_rel, "marketRelevance": market_rel,
        "sourceTopicRelevance": source_rel, "precision": precision,
    }
    return round(score, 2), detail


def _coverage(grounded_count: int, target: int = 3) -> float:
    return min(1.0, grounded_count / target) if target else 1.0


def workflow_structural_score(
    steps: List[Item], sections: List[Dict[str, Any]], persona_key: str, available: Set[str],
    persona_brief: Dict[str, Any] | None = None,
) -> Tuple[float, Dict[str, Any]]:
    if not steps:
        return 0.0, {"count": 0, "unsupportedOrNa": 0, "duplicates": 0}
    by_code = _by_code(sections)
    focus = _persona_focus_tokens(persona_brief or {})

    item_scores: List[float] = []
    support = valid = ownership = completeness = persona_rel = 0
    unsupported_or_na = 0
    titles: List[Set[str]] = []
    grounded = 0
    for s in steps:
        code = s.get("evidenceCode", "")
        text = f"{s.get('title', '')} {s.get('description', '')}"
        sup, _ = _supported(text, by_code.get(code))
        is_valid = _is_valid_code(code, available)
        item_scores.append(workflow_item_score(s, by_code, available))
        support += int(sup)
        valid += int(is_valid)
        ownership += int(is_valid and by_code.get(code) is not None)
        title = s.get("title", "") or ""
        first = title.strip().split()[0].lower().strip(":,") if title.strip() else ""
        completeness += int(first in _OPERATIONAL_VERBS and all(
            s.get(k) for k in ("title", "description", "whyItMatters", "expectedOutput")))
        persona_rel += int(bool(ev_tokens(text) & focus)) if focus else 0
        grounded += int(is_valid and sup)
        if (not is_valid) or (code == INSUFFICIENT_EVIDENCE) or (not sup):
            unsupported_or_na += 1
        titles.append(ev_tokens(title))

    n = len(steps)
    duplicates = sum(1 for i in range(n) for j in range(i + 1, n) if _jaccard(titles[i], titles[j]) >= _DUP_JACCARD)
    persona_component = (persona_rel / n) if focus else 1.0
    quality = mean(item_scores) * (0.7 + 0.3 * _coverage(grounded))
    score = 0.9 * quality + 10 * persona_component - 8 * duplicates
    detail = {
        "count": n, "evidenceSupportRate": round(support / n, 3), "citationValidityRate": round(valid / n, 3),
        "ownershipRate": round(ownership / n, 3), "operationalCompleteness": round(completeness / n, 3),
        "personaRelevance": round(persona_component, 3), "duplicates": duplicates,
        "unsupportedOrNa": unsupported_or_na, "groundedCount": grounded,
    }
    return round(max(0.0, min(100.0, score)), 2), detail


def risk_structural_score(
    risks: List[Item], sections: List[Dict[str, Any]], persona_key: str, market: str,
    available: Set[str], contradictions: int = 0,
) -> Tuple[float, Dict[str, Any]]:
    if not risks:
        return 0.0, {"count": 0, "unsupportedOrNa": 0, "duplicates": 0}
    by_code = _by_code(sections)

    item_scores: List[float] = []
    support = valid = ownership = 0
    specificity_sum = 0.0
    unsupported_or_na = 0
    contradiction_hits = 0
    grounded = 0
    titles: List[Set[str]] = []
    severities: List[str] = []
    for r in risks:
        code = r.get("evidenceCode", "")
        text = f"{r.get('title', '')} {r.get('description', '')}"
        sup, _ = _supported(text, by_code.get(code))
        is_valid = _is_valid_code(code, available)
        item_scores.append(risk_item_score(r, by_code, available))
        support += int(sup)
        valid += int(is_valid)
        ownership += int(is_valid and by_code.get(code) is not None)
        specificity_sum += _specificity(f"{text} {r.get('businessImpact', '')} {r.get('recommendedFix', '')}", 500)
        grounded += int(is_valid and sup)
        if (not is_valid) or (code == INSUFFICIENT_EVIDENCE) or (not sup):
            unsupported_or_na += 1
        if ev_tokens(text) & _CONTRADICTION_TERMS:
            contradiction_hits += 1
        titles.append(ev_tokens(r.get("title", "")))
        severities.append(r.get("severity", ""))

    n = len(risks)
    duplicates = sum(1 for i in range(n) for j in range(i + 1, n) if _jaccard(titles[i], titles[j]) >= _DUP_JACCARD)
    sev_valid = all(s in ("High", "Medium", "Low") for s in severities)
    sev_varied = len(set(severities)) > 1 or n == 1
    severity_consistency = 1.0 if (sev_valid and sev_varied) else 0.0
    contradiction_awareness = 1.0 if contradictions == 0 else min(1.0, contradiction_hits / n + 0.5)

    quality = mean(item_scores) * (0.7 + 0.3 * _coverage(grounded))
    modifiers = 0.5 * severity_consistency + 0.5 * contradiction_awareness
    score = 0.9 * quality + 10 * modifiers - 8 * duplicates
    detail = {
        "count": n, "evidenceSupportRate": round(support / n, 3), "citationValidityRate": round(valid / n, 3),
        "ownershipRate": round(ownership / n, 3), "riskSpecificity": round(specificity_sum / n, 3),
        "severityConsistency": severity_consistency, "contradictionAwareness": round(contradiction_awareness, 3),
        "duplicates": duplicates, "unsupportedOrNa": unsupported_or_na, "groundedCount": grounded,
    }
    return round(max(0.0, min(100.0, score)), 2), detail


# --------------------------------------------------------------------------- #
# item-level reconciliation
# --------------------------------------------------------------------------- #

def _reconcile(
    det_items: List[Item], cand_items: List[Item], item_score_fn: Callable[[Item], float],
    by_code: Dict[str, Dict[str, Any]], available: Set[str],
) -> Tuple[List[Item], int, int, List[str]]:
    """Preserve strong deterministic items; accept genuinely better/new grounded
    candidate items; reject unsupported/weaker/duplicate/generic. No filler."""
    merged: List[Item] = list(det_items)
    merged_titles: List[Set[str]] = [ev_tokens(i.get("title", "")) for i in merged]
    accepted = 0
    rejected = 0
    reasons: List[str] = []

    for cand in cand_items:
        code = cand.get("evidenceCode", "")
        text = f"{cand.get('title', '')} {cand.get('description', '')}"
        supported, _ = _supported(text, by_code.get(code))
        grounded = _is_valid_code(code, available) and supported
        if not grounded:
            rejected += 1
            reasons.append("unsupported-or-invalid-item")
            continue
        if _specificity(text, 500) <= 0.0:
            rejected += 1
            reasons.append("generic-item")
            continue

        cand_tokens = ev_tokens(cand.get("title", ""))
        dup_idx = next((i for i, t in enumerate(merged_titles) if _jaccard(cand_tokens, t) >= _DUP_JACCARD), None)
        if dup_idx is not None:
            if item_score_fn(cand) > item_score_fn(merged[dup_idx]):
                merged[dup_idx] = cand           # strictly-better replacement
                merged_titles[dup_idx] = cand_tokens
                accepted += 1
            else:
                rejected += 1
                reasons.append("weaker-or-duplicate-item")
            continue

        merged.append(cand)                       # genuinely new grounded item
        merged_titles.append(cand_tokens)
        accepted += 1

    return merged, accepted, rejected, reasons


# --------------------------------------------------------------------------- #
# report-level guardrails
# --------------------------------------------------------------------------- #

def _report_evidence_refs(report: Report) -> List[str]:
    return [w.get("evidenceCode", "") for w in report.get("workflowSteps", [])] + [
        r.get("evidenceCode", "") for r in report.get("risks", [])
    ]


def _source_mismatch(report: Report, available: Set[str]) -> int:
    return sum(1 for c in _report_evidence_refs(report) if c and c != INSUFFICIENT_EVIDENCE and c not in available)


def _na_count(report: Report) -> int:
    return sum(1 for c in _report_evidence_refs(report) if c == INSUFFICIENT_EVIDENCE)


def _grounding_of(report: Report, available: Set[str], custom: str) -> Tuple[float, float, int, bool]:
    schema_ok, _ = validate_schema(report)
    ca = citation_accuracy(report, available)
    cc = citation_coverage(report, available)
    hc = hallucination_warnings(report, available, custom)[0]
    return grounding_score(schema_ok, ca, cc, hc), ca, hc, schema_ok


def _passes_guardrails(det: Report, cand: Report, available: Set[str], custom: str) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    d_ground, d_ca, d_hc, _ = _grounding_of(det, available, custom)
    c_ground, c_ca, c_hc, c_schema = _grounding_of(cand, available, custom)
    if not c_schema:
        reasons.append("schema-invalid")
    if c_ground < d_ground:
        reasons.append("grounding-decreased")
    if c_ca < d_ca:
        reasons.append("citation-accuracy-decreased")
    if c_hc > d_hc:
        reasons.append("warnings-increased")
    if _source_mismatch(cand, available) > _source_mismatch(det, available):
        reasons.append("source-mismatch-increased")
    if _na_count(cand) > _na_count(det):
        reasons.append("insufficient-evidence-increased")
    return (len(reasons) == 0, reasons)


# --------------------------------------------------------------------------- #
# public entrypoint
# --------------------------------------------------------------------------- #

def reconcile_and_gate(
    det: Dict[str, Any],
    cand: Dict[str, Any],
    ctx: Dict[str, Any],
    compose_fn: Callable[[Dict[str, Any], List[Item], List[Item]], Report],
) -> Dict[str, Any]:
    """Gate full-mode candidate components against the deterministic baseline.

    `det`/`cand` each carry personaBrief, workflowSteps, risks. Returns the
    accepted components plus structural telemetry. Deterministic components are
    preserved on ties or any guardrail regression.
    """
    sections = ctx["sections"]
    available: Set[str] = ctx["available"]
    persona_key = ctx["persona_key"]
    market = ctx["market"]
    custom = ctx.get("custom", "")
    contradictions = ctx.get("contradictions", 0)
    by_code = _by_code(sections)

    det_pb, det_wf, det_rk = det["personaBrief"], det["workflowSteps"], det["risks"]
    cand_pb, cand_wf, cand_rk = cand["personaBrief"], cand["workflowSteps"], cand["risks"]

    # baseline + pure-candidate structural scores (for telemetry)
    det_pb_s, _ = persona_structural_score(det_pb, sections, market, persona_key)
    det_wf_s, _ = workflow_structural_score(det_wf, sections, persona_key, available, det_pb)
    det_rk_s, _ = risk_structural_score(det_rk, sections, persona_key, market, available, contradictions)
    cand_pb_s, _ = persona_structural_score(cand_pb, sections, market, persona_key)
    cand_wf_s, _ = workflow_structural_score(cand_wf, sections, persona_key, available, cand_pb)
    cand_rk_s, _ = risk_structural_score(cand_rk, sections, persona_key, market, available, contradictions)

    accepted_components: List[str] = []
    rejected_components: List[str] = []
    rejection_reasons: Dict[str, Any] = {}

    # --- 1) persona brief (whole-component gate) ---
    final_pb = det_pb
    if cand_pb_s > det_pb_s:
        det_report = compose_fn(det_pb, det_wf, det_rk)
        cand_report = compose_fn(cand_pb, det_wf, det_rk)
        ok, reasons = _passes_guardrails(det_report, cand_report, available, custom)
        if ok:
            final_pb = cand_pb
            accepted_components.append("personaBrief")
        else:
            rejected_components.append("personaBrief")
            rejection_reasons["personaBrief"] = reasons
    else:
        rejected_components.append("personaBrief")
        rejection_reasons["personaBrief"] = ["no-improvement"]

    # --- 2) workflow steps (item-level reconciliation + component guardrails) ---
    merged_wf, wf_acc, wf_rej, wf_item_reasons = _reconcile(
        det_wf, cand_wf, lambda it: workflow_item_score(it, by_code, available), by_code, available
    )
    final_wf = det_wf
    wf_workflow_accepted = 0
    wf_workflow_rejected = wf_rej
    merged_wf_s, _ = workflow_structural_score(merged_wf, sections, persona_key, available, final_pb)
    if wf_acc > 0 and merged_wf_s > det_wf_s:
        det_report = compose_fn(final_pb, det_wf, det_rk)
        cand_report = compose_fn(final_pb, merged_wf, det_rk)
        ok, reasons = _passes_guardrails(det_report, cand_report, available, custom)
        if ok:
            final_wf = merged_wf
            accepted_components.append("workflowSteps")
            wf_workflow_accepted = wf_acc
        else:
            rejected_components.append("workflowSteps")
            rejection_reasons["workflowSteps"] = reasons
            wf_workflow_rejected += wf_acc  # accepted items reverted by guardrail
    else:
        rejected_components.append("workflowSteps")
        rejection_reasons["workflowSteps"] = wf_item_reasons or ["no-improvement"]
        wf_workflow_rejected += wf_acc

    # --- 3) risks (item-level reconciliation + component guardrails) ---
    merged_rk, rk_acc, rk_rej, rk_item_reasons = _reconcile(
        det_rk, cand_rk, lambda it: risk_item_score(it, by_code, available), by_code, available
    )
    final_rk = det_rk
    rk_risks_accepted = 0
    rk_risks_rejected = rk_rej
    merged_rk_s, _ = risk_structural_score(merged_rk, sections, persona_key, market, available, contradictions)
    if rk_acc > 0 and merged_rk_s > det_rk_s:
        det_report = compose_fn(final_pb, final_wf, det_rk)
        cand_report = compose_fn(final_pb, final_wf, merged_rk)
        ok, reasons = _passes_guardrails(det_report, cand_report, available, custom)
        if ok:
            final_rk = merged_rk
            accepted_components.append("risks")
            rk_risks_accepted = rk_acc
        else:
            rejected_components.append("risks")
            rejection_reasons["risks"] = reasons
            rk_risks_rejected += rk_acc
    else:
        rejected_components.append("risks")
        rejection_reasons["risks"] = rk_item_reasons or ["no-improvement"]
        rk_risks_rejected += rk_acc

    # --- structural scores + decision ---
    final_pb_s, _ = persona_structural_score(final_pb, sections, market, persona_key)
    final_wf_s, _ = workflow_structural_score(final_wf, sections, persona_key, available, final_pb)
    final_rk_s, _ = risk_structural_score(final_rk, sections, persona_key, market, available, contradictions)
    det_struct = round(mean([det_pb_s, det_wf_s, det_rk_s]), 2)
    cand_struct = round(mean([cand_pb_s, cand_wf_s, cand_rk_s]), 2)
    final_struct = round(mean([final_pb_s, final_wf_s, final_rk_s]), 2)

    if len(accepted_components) == 3:
        decision = "all-accepted"
    elif accepted_components:
        decision = "partial"
    else:
        decision = "all-rejected"
    fallback = not accepted_components

    telemetry = {
        "deterministicStructuralScore": det_struct,
        "candidateStructuralScore": cand_struct,
        "finalStructuralScore": final_struct,
        "structuralGateDecision": decision,
        "acceptedStructuralComponents": accepted_components,
        "rejectedStructuralComponents": rejected_components,
        "acceptedRiskCount": rk_risks_accepted,
        "rejectedRiskCount": rk_risks_rejected,
        "acceptedWorkflowStepCount": wf_workflow_accepted,
        "rejectedWorkflowStepCount": wf_workflow_rejected,
        "structuralRejectionReasons": rejection_reasons,
        "fullModeAnalyticalFallback": fallback,
    }
    return {
        "personaBrief": final_pb,
        "workflowSteps": final_wf,
        "risks": final_rk,
        "telemetry": telemetry,
    }


def default_structural_telemetry() -> Dict[str, Any]:
    return {
        "deterministicStructuralScore": 0.0,
        "candidateStructuralScore": 0.0,
        "finalStructuralScore": 0.0,
        "structuralGateDecision": "no-updates",
        "acceptedStructuralComponents": [],
        "rejectedStructuralComponents": [],
        "acceptedRiskCount": 0,
        "rejectedRiskCount": 0,
        "acceptedWorkflowStepCount": 0,
        "rejectedWorkflowStepCount": 0,
        "structuralRejectionReasons": {},
        "fullModeAnalyticalFallback": False,
    }
