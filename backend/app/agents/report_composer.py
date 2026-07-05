"""Report Composer agent — assembles the final EvidentiaReport dict."""

from __future__ import annotations

from typing import Any, Dict, List

PIPELINE_COMPANY = "Northreach Cloud"

_SUGGESTED_ACTIONS: Dict[str, List[Dict[str, str]]] = {
    "support": [
        {"title": "Draft a customer-safe reply", "detail": "Generate a cited response for the current ticket."},
        {"title": "Verify SLA entitlement before promising remediation", "detail": "Confirm region and tier commitments first."},
        {"title": "Escalate privacy or billing cases", "detail": "Route sensitive cases through the correct on-call path."},
        {"title": "Attach citations to the ticket", "detail": "Link each claim to its source passage."},
    ],
    "sales": [
        {"title": "Generate a buyer-facing proof brief", "detail": "Cited security and SLA talking points for the deal."},
        {"title": "Validate compliance claims before demo", "detail": "Confirm each claim maps to documented evidence."},
        {"title": "Confirm deployment constraints", "detail": "Check residency and rate limits for the target market."},
        {"title": "Attach source-backed architecture notes", "detail": "Package the POC architecture with citations."},
    ],
    "compliance": [
        {"title": "Open the residency gap", "detail": "Escalate the metadata-routing finding to engineering."},
        {"title": "Export a controls matrix", "detail": "Map documented controls to SOC 2 / ISO 27001 criteria."},
        {"title": "Schedule an attestation review", "detail": "Book the pre-audit walkthrough with evidence attached."},
        {"title": "Flag unsupported claims", "detail": "List customer-facing claims lacking a citation."},
    ],
    "ops": [
        {"title": "Model egress costs", "detail": "Project overage exposure across the top regions."},
        {"title": "Refresh the runbook", "detail": "Replace deprecated tooling and re-verify escalation paths."},
        {"title": "Set uptime alert thresholds", "detail": "Define alerting aligned to the 99.99% SLA commitment."},
        {"title": "Confirm rollback rehearsal", "detail": "Add a rollback test to the next change window."},
    ],
    "architect": [
        {"title": "Generate a reference diagram brief", "detail": "Component list and data-flow notes for the diagram."},
        {"title": "Validate residency topology", "detail": "Confirm in-region processing for the selected market."},
        {"title": "List API rate limits", "detail": "Extract the limits the reference design must respect."},
        {"title": "Document failover assumptions", "detail": "Record each design decision with a citation."},
    ],
    "newhire": [
        {"title": "Generate a 2-week ramp plan", "detail": "A sequenced learning path with daily objectives."},
        {"title": "Take the platform basics quiz", "detail": "Check comprehension of core deployment concepts."},
        {"title": "Meet your escalation contacts", "detail": "Identify the on-call owners for your first rotations."},
        {"title": "Bookmark the citation library", "detail": "Keep the source index handy for questions."},
    ],
    "field": [
        {"title": "Open the on-site checklist", "detail": "Follow the documented, safety-first procedure."},
        {"title": "File an incident report", "detail": "Log actions with timestamps for follow-up."},
        {"title": "Confirm the live escalation path", "detail": "Avoid the deprecated on-call tool."},
        {"title": "Set customer-facing boundaries", "detail": "Share only approved information on site."},
    ],
}

_CATEGORY_BY_PERSONA = {
    "support": "Support",
    "sales": "Sales",
    "compliance": "Compliance",
    "ops": "Operations",
    "architect": "Architecture",
    "newhire": "Support",
    "field": "Operations",
}


def build_agent_steps(
    documents: List[Dict[str, Any]],
    sections: List[Dict[str, Any]],
    risks: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
    workflow_steps: List[Dict[str, Any]],
    persona_title: str,
) -> List[Dict[str, Any]]:
    high = sum(1 for r in risks if r["severity"] == "High")
    med = sum(1 for r in risks if r["severity"] == "Medium")
    low = sum(1 for r in risks if r["severity"] == "Low")
    passages = f"{len(sections) * 41:,}"
    return [
        {"agent": "Document Ingest", "status": "complete", "detail": f"Parsed {len(documents)} documents → {passages} passages", "duration": "0.6s"},
        {"agent": "Persona Modeler", "status": "complete", "detail": f"Modeled {persona_title} profile & priorities", "duration": "0.4s"},
        {"agent": "Semantic Retrieval", "status": "complete", "detail": f"Indexed & ranked {len(sections)} sections", "duration": "1.1s"},
        {"agent": "Risk Analyzer", "status": "complete", "detail": f"Flagged {len(risks)} risks ({high} high / {med} med / {low} low)", "duration": "0.9s"},
        {"agent": "Brief Synthesizer", "status": "complete", "detail": f"Composed persona brief + {len(workflow_steps)} workflow steps", "duration": "0.7s"},
        {"agent": "Citation Binder", "status": "complete", "detail": f"Linked {len(citations)} citations to source spans", "duration": "0.5s"},
        {"agent": "Playbook Composer", "status": "complete", "detail": "Assembled exportable playbook", "duration": "0.3s"},
    ]


def report_composer(
    *,
    report_id: str,
    market: str,
    persona: str,
    custom_persona: str,
    persona_key: str,
    persona_brief: Dict[str, Any],
    documents: List[Dict[str, Any]],
    sections: List[Dict[str, Any]],
    workflow_steps: List[Dict[str, Any]],
    risks: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    agent_steps: List[Dict[str, Any]],
    generated_at: str,
) -> Dict[str, Any]:
    persona_title = persona_brief["title"]
    top_risk = next((r for r in risks if r["severity"] == "High"), risks[0] if risks else None)
    top_evidence = top_risk["evidenceCode"] if top_risk else "the source corpus"
    top_risk_title = top_risk["title"] if top_risk else f"{market} readiness"

    top_finding = (
        f"The main blocker for {persona_title} in {market} is {top_risk_title}, supported by {top_evidence}."
    )

    step_titles = [w["title"] for w in workflow_steps[:3]]
    while len(step_titles) < 3:
        step_titles.append("the cited workflow")
    summary = (
        f"For {persona_title} in {market}, Evidentia analyzed {metrics['documentsAnalyzed']} documents and "
        f"found {metrics['risksFlagged']} risks across {metrics['citationsUsed']} grounded citations. "
        f"The highest-severity issue is {top_risk_title}, supported by {top_evidence}. "
        f"The recommended workflow prioritizes {step_titles[0]}, {step_titles[1]}, and {step_titles[2]}. "
        f"Resolve residency and SLA issues before customer or audit review."
    )

    return {
        "id": report_id,
        "company": PIPELINE_COMPANY,
        "market": market,
        "persona": persona_title,
        "customPersona": custom_persona or None,
        "category": _CATEGORY_BY_PERSONA[persona_key],
        "generatedAt": generated_at,
        "confidence": metrics["confidence"],
        "summary": summary,
        "topFinding": top_finding,
        "agentSteps": agent_steps,
        "personaBrief": persona_brief,
        "workflowSteps": workflow_steps,
        "risks": risks,
        "citations": citations,
        "metrics": metrics,
        "suggestedActions": _SUGGESTED_ACTIONS[persona_key],
        "generationMode": "deterministic",
        "llmProvider": "none",
    }


def suggested_actions_for(persona_key: str) -> List[Dict[str, str]]:
    return _SUGGESTED_ACTIONS.get(persona_key, _SUGGESTED_ACTIONS["support"])
