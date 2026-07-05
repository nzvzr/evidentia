"""Workflow Builder agent — 4-6 persona/market-aware steps bound to evidence."""

from __future__ import annotations

from typing import Any, Dict, List

_TEMPLATES: Dict[str, List[Dict[str, str]]] = {
    "support": [
        {"title": "Triage against the severity matrix", "description": "Classify the ticket using the Incident Response Runbook severity definitions.", "whyItMatters": "A correct severity sets the response window and escalation path.", "expectedOutput": "A severity classification with the matching runbook clause.", "prefer": "INC"},
        {"title": "Confirm SLA entitlements", "description": "Verify the customer's region and tier commitments before promising a remediation window.", "whyItMatters": "Promising a window the SLA does not cover creates credit disputes.", "expectedOutput": "A confirmed remediation window tied to the SLA tier.", "prefer": "SLA"},
        {"title": "Pull verified remediation steps", "description": "Retrieve the documented fix and attach the source passage to your reply.", "whyItMatters": "Cited steps keep customer-facing replies accurate and defensible.", "expectedOutput": "A cited, customer-safe remediation reply.", "prefer": "DEP"},
        {"title": "Escalate P1/P2 correctly", "description": "Route severe incidents through the current on-call path, not a deprecated tool.", "whyItMatters": "A stale escalation path can silently drop Sev-1 pages.", "expectedOutput": "A correctly routed escalation with the live on-call owner.", "prefer": "INC"},
        {"title": "Draft a customer-safe reply", "description": "Compose the response using approved wording and attached citations.", "whyItMatters": "Consistent, cited wording protects the customer relationship.", "expectedOutput": "A ready-to-send, source-backed customer reply.", "prefer": "SEC"},
    ],
    "sales": [
        {"title": "Map requirements to capabilities", "description": "Align the buyer's stated needs to documented platform features.", "whyItMatters": "Grounding claims in docs prevents overpromising in the deal.", "expectedOutput": "A requirements-to-capabilities matrix.", "prefer": "SEC"},
        {"title": "Prepare SecQ responses", "description": "Draft security-questionnaire answers with inline citations.", "whyItMatters": "Cited answers accelerate security review and build trust.", "expectedOutput": "A set of cited security-questionnaire answers.", "prefer": "SEC"},
        {"title": "Address data residency", "description": "Confirm the residency posture for the target market before the technical review.", "whyItMatters": "Residency is a common deal-blocker in regulated markets.", "expectedOutput": "A residency talk track for the selected market.", "prefer": "RES"},
        {"title": "Confirm SLA and limits", "description": "Validate availability commitments and API limits the design depends on.", "whyItMatters": "Accurate limits keep the POC scope realistic.", "expectedOutput": "A validated SLA and rate-limit summary.", "prefer": "SLA"},
        {"title": "Assemble a POC architecture", "description": "Produce a reference architecture the customer's team can validate.", "whyItMatters": "A concrete architecture converts interest into a technical win.", "expectedOutput": "A POC reference architecture with success criteria.", "prefer": "API"},
    ],
    "compliance": [
        {"title": "Identify regulated claims", "description": "List claims in customer-facing material that require evidence.", "whyItMatters": "Unsupported claims are the most common audit finding.", "expectedOutput": "A list of regulated claims needing evidence.", "prefer": "SEC"},
        {"title": "Verify residency obligations", "description": "Assess where control-plane and customer data are processed for this market.", "whyItMatters": "Residency defaults may not meet regional obligations.", "expectedOutput": "A residency posture summary with deviations.", "prefer": "RES"},
        {"title": "Check evidence coverage", "description": "Map each control claim to a source citation.", "whyItMatters": "Coverage gaps become blockers at attestation time.", "expectedOutput": "A control-to-citation coverage map.", "prefer": "SEC"},
        {"title": "Flag missing controls", "description": "Record controls that are asserted but not documented.", "whyItMatters": "Documented gaps can be remediated before the audit.", "expectedOutput": "A remediation log with owners.", "prefer": "SLA"},
        {"title": "Prepare audit-ready notes", "description": "Compile findings and evidence into a review-ready packet.", "whyItMatters": "An organized packet shortens the attestation cycle.", "expectedOutput": "An audit-ready notes packet.", "prefer": "RES"},
    ],
    "ops": [
        {"title": "Review SLA commitments", "description": "Check availability targets and multi-region outage terms.", "whyItMatters": "Ambiguous terms create disputes during correlated outages.", "expectedOutput": "An SLA commitment summary with exposure notes.", "prefer": "SLA"},
        {"title": "Audit the incident runbook", "description": "Identify stale references and tooling gaps in the on-call process.", "whyItMatters": "A stale runbook slows time-to-restore in a real incident.", "expectedOutput": "A runbook audit with remediation items.", "prefer": "INC"},
        {"title": "Model cost exposure", "description": "Estimate egress and overage cost under expected load.", "whyItMatters": "Undocumented overage becomes an unforecastable cost.", "expectedOutput": "A cost-exposure model across regions.", "prefer": "PRC"},
        {"title": "Confirm deployment safety", "description": "Verify rollback and failover are tested before change windows.", "whyItMatters": "Untested rollback turns a small change into an outage.", "expectedOutput": "A validated deployment-safety checklist.", "prefer": "DEP"},
        {"title": "Align on-call ownership", "description": "Map staffing to the severity matrix response windows.", "whyItMatters": "Clear ownership prevents dropped escalations.", "expectedOutput": "An on-call ownership plan aligned to SLAs.", "prefer": "INC"},
    ],
    "architect": [
        {"title": "Select deployment topology", "description": "Choose a topology that satisfies the market's residency rules.", "whyItMatters": "The topology decision constrains every later design choice.", "expectedOutput": "A chosen topology with residency justification.", "prefer": "DEP"},
        {"title": "Map required API surfaces", "description": "Identify endpoints and rate limits the design depends on.", "whyItMatters": "Unaccounted rate limits cause failures under load.", "expectedOutput": "An API-surface map with rate-limit notes.", "prefer": "API"},
        {"title": "Validate data residency path", "description": "Confirm in-region processing for the selected market.", "whyItMatters": "Residency defaults may route metadata out of region.", "expectedOutput": "A validated residency data-flow.", "prefer": "RES"},
        {"title": "Design multi-region failover", "description": "Meet the SLA with automated failover and tested rollback.", "whyItMatters": "Failover design is what makes the SLA achievable.", "expectedOutput": "A failover design meeting the SLA target.", "prefer": "SLA"},
        {"title": "Document assumptions with citations", "description": "Record every design decision with a supporting citation.", "whyItMatters": "Cited assumptions survive security review.", "expectedOutput": "A cited assumptions log for review.", "prefer": "SEC"},
    ],
    "newhire": [
        {"title": "Complete onboarding essentials", "description": "Work through the core sections of the onboarding handbook.", "whyItMatters": "Shared context is the foundation for safe first actions.", "expectedOutput": "A completed onboarding-essentials checklist.", "prefer": "ONB"},
        {"title": "Learn deployment fundamentals", "description": "Understand how the platform is deployed and rolled back.", "whyItMatters": "Deployment basics prevent unsafe early changes.", "expectedOutput": "Notes on deployment and rollback fundamentals.", "prefer": "DEP"},
        {"title": "Study the severity matrix", "description": "Know how incidents are classified and escalated.", "whyItMatters": "Knowing escalation prevents freezing during an incident.", "expectedOutput": "A personal severity-matrix cheat sheet.", "prefer": "INC"},
        {"title": "Confirm SLA basics", "description": "Learn the availability commitment and what it excludes.", "whyItMatters": "SLA literacy avoids accidental overpromising.", "expectedOutput": "A short SLA basics summary.", "prefer": "SLA"},
        {"title": "Bookmark the citation library", "description": "Keep the source index handy for day-to-day questions.", "whyItMatters": "Fast source access keeps answers accurate.", "expectedOutput": "A saved index of key source citations.", "prefer": "SEC"},
    ],
    "field": [
        {"title": "Triage the on-site issue", "description": "Classify the on-site issue against the severity matrix.", "whyItMatters": "Severity drives whether to proceed or escalate immediately.", "expectedOutput": "A severity classification for the on-site issue.", "prefer": "INC"},
        {"title": "Confirm safe procedure", "description": "Verify the documented procedure and safety steps before acting.", "whyItMatters": "Following the documented procedure protects people and equipment.", "expectedOutput": "A confirmed, safe on-site procedure.", "prefer": "DEP"},
        {"title": "Escalate correctly", "description": "Route severe issues through the current on-call escalation path.", "whyItMatters": "A stale escalation path can strand an urgent on-site issue.", "expectedOutput": "A correctly routed escalation.", "prefer": "INC"},
        {"title": "Document actions taken", "description": "Record each action with timestamps for the incident log.", "whyItMatters": "Documented actions support follow-up and accountability.", "expectedOutput": "An action log entry for the incident.", "prefer": "ONB"},
        {"title": "Set customer-facing boundaries", "description": "Communicate only approved information to on-site stakeholders.", "whyItMatters": "Clear boundaries prevent unsupported commitments on site.", "expectedOutput": "A customer-safe on-site status update.", "prefer": "SEC"},
    ],
}


def _pick_evidence(sections: List[Dict[str, Any]], prefer: str, fallback_index: int) -> str:
    for s in sections:
        if s["citationId"].startswith(prefer):
            return s["citationId"]
    if sections:
        return sections[fallback_index % len(sections)]["citationId"]
    return f"{prefer}-1"


def workflow_builder(persona_key: str, market: str, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    templates = _TEMPLATES.get(persona_key, _TEMPLATES["support"])
    count = min(6, max(4, 5 if len(sections) >= 12 else 5))
    steps: List[Dict[str, Any]] = []
    for i, t in enumerate(templates[:count]):
        steps.append(
            {
                "step": i + 1,
                "title": t["title"],
                "description": t["description"],
                "whyItMatters": t["whyItMatters"],
                "expectedOutput": t["expectedOutput"],
                "evidenceCode": _pick_evidence(sections, t["prefer"], i),
            }
        )
    return steps
