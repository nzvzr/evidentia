"""Tests for the full-mode structural quality gate + item reconciliation."""

from app.agents.citation_binder import citation_binder
from app.agents.document_reader import document_reader
from app.agents.metrics_agent import metrics_agent
from app.agents.report_composer import build_agent_steps, report_composer
from app.agents.risk_analyzer import risk_analyzer
from app.agents.workflow_builder import workflow_builder
from app.agents.structural_gate import (
    _passes_guardrails,
    reconcile_and_gate,
    risk_structural_score,
    workflow_structural_score,
)
from app.tools.citation_tools import INSUFFICIENT_EVIDENCE

RES = "data-residency-sovereignty-policy"
SEC = "security-compliance-whitepaper"
SLA = "sla-uptime-commitment"
MARKET = "Healthcare"
PERSONA_KEY = "compliance"


def _setup():
    documents, sections = document_reader([RES, SEC, SLA])
    available = {s["citationId"] for s in sections}
    persona_brief = {
        "title": "Compliance Officer", "description": "Assess residency and security controls for Healthcare.",
        "goals": ["ground findings"], "priorities": ["residency", "controls"],
        "relevantTopics": ["residency", "security", "compliance"], "riskFocus": ["residency"],
        "outputStyle": "precise", "isCustom": False,
    }
    workflow, _ = workflow_builder(PERSONA_KEY, MARKET, sections)
    risks, _ = risk_analyzer(PERSONA_KEY, MARKET, sections)

    def compose(pb, wf, rk):
        c = citation_binder(sections, wf, rk)
        m = metrics_agent(documents, sections, c, rk, wf, MARKET, PERSONA_KEY, pb["title"])
        ag = build_agent_steps(documents, sections, rk, c, wf, pb["title"])
        return report_composer(
            report_id="t", market=MARKET, persona="Compliance Officer", custom_persona="",
            persona_key=PERSONA_KEY, persona_brief=pb, documents=documents, sections=sections,
            workflow_steps=wf, risks=rk, citations=c, metrics=m, agent_steps=ag, generated_at="now",
        )

    ctx = {"sections": sections, "available": available, "persona_key": PERSONA_KEY,
           "market": MARKET, "custom": "", "contradictions": 0}
    return documents, sections, available, persona_brief, workflow, risks, compose, ctx


def _grounded_risk(section, severity="Medium", suffix="exposure"):
    return {
        "severity": severity,
        "title": f"{section['sectionTitle']} {suffix}",
        "description": section["excerpt"][:140],
        "businessImpact": "Regulatory and audit exposure if controls are not verified.",
        "evidenceCode": section["citationId"],
        "recommendedFix": "Add documented controls and re-verify before audit.",
        "owner": "Compliance",
    }


def _weak_risk(code="RES-14"):
    return {
        "severity": "Low", "title": "Improve overall synergy",
        "description": "Leverage best practices to drive success and value.",
        "businessImpact": "Better outcomes.", "evidenceCode": code,
        "recommendedFix": "Do better.", "owner": "x",
    }


# 1) A weaker full-mode workflow is rejected.
def test_weaker_workflow_rejected():
    *_, persona_brief, workflow, risks, compose, ctx = _setup()
    weak_wf = [
        {"step": 1, "title": "Improve things", "description": "Leverage best practices.",
         "whyItMatters": "It helps.", "expectedOutput": "Success.", "evidenceCode": workflow[0]["evidenceCode"]}
    ]
    out = reconcile_and_gate(
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": risks},
        {"personaBrief": persona_brief, "workflowSteps": weak_wf, "risks": risks},
        ctx, compose,
    )
    assert "workflowSteps" not in out["telemetry"]["acceptedStructuralComponents"]
    assert out["workflowSteps"] == workflow


# 2) A weaker or unsupported risk is rejected.
def test_weaker_risk_rejected():
    *_, persona_brief, workflow, risks, compose, ctx = _setup()
    out = reconcile_and_gate(
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": risks},
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": [_weak_risk()]},
        ctx, compose,
    )
    assert "risks" not in out["telemetry"]["acceptedStructuralComponents"]
    assert out["risks"] == risks


# 3) A new genuinely grounded risk can be accepted.
def test_new_grounded_risk_accepted():
    _docs, sections, available, persona_brief, workflow, _risks, compose, ctx = _setup()
    # start from a small deterministic baseline (2 risks) so coverage can rise
    det_risks = [_grounded_risk(sections[0], "High"), _grounded_risk(sections[4], "Medium", "gap")]
    # a new grounded risk derived from a different section (unique title)
    new_risk = _grounded_risk(sections[8], "Medium", "risk")  # SLA section
    out = reconcile_and_gate(
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": det_risks},
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": det_risks + [new_risk]},
        ctx, compose,
    )
    assert "risks" in out["telemetry"]["acceptedStructuralComponents"]
    assert out["telemetry"]["acceptedRiskCount"] >= 1
    assert len(out["risks"]) == len(det_risks) + 1


# 4) Strong deterministic risks are preserved even when a candidate is accepted.
def test_strong_deterministic_risks_preserved():
    _docs, sections, available, persona_brief, workflow, _risks, compose, ctx = _setup()
    det_risks = [_grounded_risk(sections[0], "High"), _grounded_risk(sections[4], "Medium", "gap")]
    new_risk = _grounded_risk(sections[8], "Medium", "risk")
    out = reconcile_and_gate(
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": det_risks},
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": [new_risk]},
        ctx, compose,
    )
    for d in det_risks:
        assert d in out["risks"]


# 5) Partial reconciliation accepts one risk while rejecting another.
def test_partial_reconciliation():
    _docs, sections, available, persona_brief, workflow, _risks, compose, ctx = _setup()
    det_risks = [_grounded_risk(sections[0], "High"), _grounded_risk(sections[4], "Medium", "gap")]
    good = _grounded_risk(sections[8], "Medium", "risk")
    bad = _weak_risk()
    out = reconcile_and_gate(
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": det_risks},
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": [good, bad]},
        ctx, compose,
    )
    assert out["telemetry"]["acceptedRiskCount"] == 1
    assert out["telemetry"]["rejectedRiskCount"] >= 1
    assert good in out["risks"] and bad not in out["risks"]


# 6) Increased N/A items or source mismatches cause rejection (guardrail-level).
def test_guardrail_rejects_na_and_source_mismatch():
    _docs, sections, available, persona_brief, workflow, risks, compose, _ctx = _setup()
    det_report = compose(persona_brief, workflow, risks)

    invented = [dict(r) for r in risks]
    invented[0]["evidenceCode"] = "ZZZ-999"  # invented -> source mismatch up
    ok, reasons = _passes_guardrails(det_report, compose(persona_brief, workflow, invented), available, "")
    assert not ok and "source-mismatch-increased" in reasons

    na = [dict(r) for r in risks]
    na[0]["evidenceCode"] = INSUFFICIENT_EVIDENCE  # more N/A than baseline
    ok2, reasons2 = _passes_guardrails(det_report, compose(persona_brief, workflow, na), available, "")
    assert not ok2 and "insufficient-evidence-increased" in reasons2


# 7) Equal-quality full output preserves deterministic content.
def test_equal_output_preserves_deterministic():
    *_, persona_brief, workflow, risks, compose, ctx = _setup()
    out = reconcile_and_gate(
        {"personaBrief": persona_brief, "workflowSteps": workflow, "risks": risks},
        {"personaBrief": dict(persona_brief), "workflowSteps": [dict(w) for w in workflow],
         "risks": [dict(r) for r in risks]},
        ctx, compose,
    )
    assert out["telemetry"]["structuralGateDecision"] == "all-rejected"
    assert out["telemetry"]["fullModeAnalyticalFallback"] is True
    assert out["personaBrief"] == persona_brief
    assert out["workflowSteps"] == workflow
    assert out["risks"] == risks
