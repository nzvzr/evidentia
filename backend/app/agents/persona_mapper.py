"""Persona Mapper / Modeler agent."""

from __future__ import annotations

from typing import Any, Dict, List

PERSONA_PROFILES: Dict[str, Dict[str, Any]] = {
    "support": {
        "key": "support",
        "title": "Support Agent",
        "description": "Resolves customer incidents quickly with SLA-accurate, source-backed answers. This brief surfaces the incident, SLA, and deployment knowledge needed to respond confidently and escalate correctly.",
        "goals": ["Resolve tickets fast", "Keep replies customer-safe", "Escalate correctly"],
        "priorities": ["Time to resolution", "SLA accuracy", "Escalation clarity"],
        "relevantTopics": ["Severity matrix", "SLA entitlements", "Escalation paths", "Privacy escalation"],
        "riskFocus": ["Deprecated on-call tooling", "SLA ambiguity", "Privacy handling"],
        "outputStyle": "Customer-safe, cited, action-first",
    },
    "sales": {
        "key": "sales",
        "title": "Sales Engineer",
        "description": "Translates platform depth into buyer confidence with defensible, cited proof points. This brief arms the deal team with security, SLA, and architecture talking points for the target market.",
        "goals": ["Win technical trust", "Answer objections", "Prove compliance posture"],
        "priorities": ["Objection handling", "Security posture", "Competitive proof"],
        "relevantTopics": ["Security controls", "SLA commitments", "Residency", "API limits"],
        "riskFocus": ["Unsupported compliance claims", "Residency gaps", "SLA ambiguity"],
        "outputStyle": "Buyer-facing, evidence-backed",
    },
    "compliance": {
        "key": "compliance",
        "title": "Compliance Officer",
        "description": "Reviews regulatory obligations through a lens of risk and evidence. This brief consolidates residency, encryption, and audit controls and elevates the gaps that must be remediated before attestation.",
        "goals": ["Ensure obligations are met", "Close control gaps", "Prepare for audit"],
        "priorities": ["Data residency", "Audit readiness", "Control coverage"],
        "relevantTopics": ["Residency", "Encryption", "Audit logging", "Regulated workloads"],
        "riskFocus": ["Residency gap", "Missing controls", "Unsupported claims"],
        "outputStyle": "Audit-ready, source-backed",
    },
    "ops": {
        "key": "ops",
        "title": "Operations Manager",
        "description": "Owns uptime, cost, and process integrity. This brief connects SLA commitments, the incident runbook, and pricing structure to surface operational and financial exposure early.",
        "goals": ["Protect uptime", "Control cost", "Keep process current"],
        "priorities": ["Uptime", "Cost control", "Process integrity"],
        "relevantTopics": ["Availability", "Incident response", "On-call ownership", "Overage cost"],
        "riskFocus": ["Deprecated tooling", "SLA credit ambiguity", "Egress cost exposure"],
        "outputStyle": "Operational, ownership-driven",
    },
    "architect": {
        "key": "architect",
        "title": "Solutions Architect",
        "description": "Turns requirements into resilient designs. This brief aligns the deployment guide, API surface, and residency policy so a reference architecture holds up to security review in the target market.",
        "goals": ["Design compliant topology", "Cover API surfaces", "Meet the SLA"],
        "priorities": ["Reference architecture", "Data residency", "API coverage"],
        "relevantTopics": ["Deployment topology", "Failover", "Residency", "Rate limits"],
        "riskFocus": ["Residency gap", "Missing rate limits", "Untested rollback"],
        "outputStyle": "Design-grade, assumption-logged",
    },
    "newhire": {
        "key": "newhire",
        "title": "New Hire",
        "description": "Needs the shortest path to competence. This brief sequences onboarding, deployment basics, and the incident process into a safe first-actions learning path with sources for going deeper.",
        "goals": ["Ramp quickly", "Know safe first actions", "Learn escalation basics"],
        "priorities": ["Fast ramp", "Process fluency", "Knowing where to look"],
        "relevantTopics": ["Onboarding", "Deployment basics", "Severity matrix", "Escalation"],
        "riskFocus": ["Skipping validation", "Unsafe first actions", "Unknown escalation path"],
        "outputStyle": "Guided, sequenced, safe",
    },
    "field": {
        "key": "field",
        "title": "Field Technician",
        "description": "Handles on-site issues with safety and clear escalation. This brief prioritizes triage, safe procedures, action documentation, and customer-facing boundaries for on-site work.",
        "goals": ["Triage on-site issues", "Work safely", "Document and escalate"],
        "priorities": ["On-site triage", "Safety", "Escalation clarity"],
        "relevantTopics": ["Severity matrix", "Escalation", "Deployment basics", "Customer boundaries"],
        "riskFocus": ["Deprecated escalation tooling", "Unclear on-site boundaries", "Undocumented actions"],
        "outputStyle": "Field-ready, safety-first",
    },
}

_TITLE_TO_KEY = {
    "support agent": "support",
    "sales engineer": "sales",
    "compliance officer": "compliance",
    "operations manager": "ops",
    "solutions architect": "architect",
    "new hire": "newhire",
    "field technician": "field",
}


def _infer_key_from_text(text: str) -> str:
    t = text.lower()

    def has(*words: str) -> bool:
        return any(w in t for w in words)

    if has("field", "technician", "on-site", "on site", "equipment", "installer"):
        return "field"
    if has("compliance", "audit", "regulat", "privacy officer", "gdpr", "hipaa"):
        return "compliance"
    if has("architect", "architecture", "deployment", "infrastructure", "topology"):
        return "architect"
    if has("operation", "uptime", "reliability", "sre", "incident"):
        return "ops"
    if has("sales", "account executive", "buyer", "pre-sales", "presales"):
        return "sales"
    if has("onboard", "new hire", "junior", "trainee", "ramp"):
        return "newhire"
    if has("support", "customer", "ticket", "helpdesk", "service desk"):
        return "support"
    return "architect"


def resolve_persona_key(persona: str, custom_persona: str = "") -> str:
    if custom_persona and custom_persona.strip():
        return _infer_key_from_text(custom_persona)
    return _TITLE_TO_KEY.get((persona or "").strip().lower(), "support")


def persona_mapper(market: str, persona: str, custom_persona: str, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    is_custom = bool(custom_persona and custom_persona.strip())
    key = resolve_persona_key(persona, custom_persona)
    base = PERSONA_PROFILES[key]

    if is_custom:
        role = custom_persona.strip()
        return {
            "title": role,
            "description": (
                f"Evidentia modeled a role profile from your description and mapped Northreach Cloud's "
                f'documentation to it. Priorities below are inferred from "{role}" for the {market} market, '
                f"using the {base['title']} profile as a baseline."
            ),
            "goals": base["goals"],
            "priorities": base["priorities"],
            "relevantTopics": base["relevantTopics"],
            "riskFocus": base["riskFocus"],
            "outputStyle": base["outputStyle"],
            "isCustom": True,
        }

    return {
        "title": base["title"],
        "description": base["description"],
        "goals": base["goals"],
        "priorities": base["priorities"],
        "relevantTopics": base["relevantTopics"],
        "riskFocus": base["riskFocus"],
        "outputStyle": base["outputStyle"],
        "isCustom": False,
    }
