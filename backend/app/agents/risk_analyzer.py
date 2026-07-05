"""Risk Analyzer agent — 3-5 grounded risks, guaranteed >=1 High and >=1 Medium."""

from __future__ import annotations

from typing import Any, Dict, List

from app.tools.scoring_tools import HIGH_COMPLIANCE_MARKETS

_RISK_POOL: List[Dict[str, Any]] = [
    {"key": "residency", "severity": "High", "title": "Data residency gap for EMEA deployments", "description": "Default control-plane routing stores metadata in us-east-1; regulated markets require in-region processing that is not enabled by default.", "businessImpact": "Blocks compliant onboarding; regulatory and deal exposure.", "recommendedFix": "Enable in-region processing and change default routing before regional GA.", "owner": "Platform Eng", "prefix": "RES", "fallbackCode": "RES-14", "personas": ["compliance", "architect", "sales"]},
    {"key": "sla-multiregion", "severity": "Medium", "title": "SLA credit terms undefined for multi-region outages", "description": "The SLA specifies single-region remedies but is silent on simultaneous multi-region failure.", "businessImpact": "Ambiguous remedy in a correlated outage; credit disputes.", "recommendedFix": "Define multi-region credit terms and legal-review the SLA addendum.", "owner": "Legal / RevOps", "prefix": "SLA", "fallbackCode": "SLA-3", "personas": ["ops", "support", "sales", "compliance"]},
    {"key": "incident-tool", "severity": "Medium", "title": "Incident runbook references a deprecated on-call tool", "description": "The escalation section names PagerTree, which was retired — pages may not deliver.", "businessImpact": "Sev-1 pages may not deliver, extending time-to-restore.", "recommendedFix": "Replace tool references and re-test the escalation path.", "owner": "SRE On-call", "prefix": "INC", "fallbackCode": "INC-2.1", "personas": ["ops", "support", "field", "newhire"]},
    {"key": "pricing-egress", "severity": "Low", "title": "Pricing sheet omits egress overage tiers", "description": "No documented rate for data egress beyond the included allowance; finance review flagged this.", "businessImpact": "Unforecastable egress cost for customers and finance.", "recommendedFix": "Publish egress overage tiers in the pricing sheet.", "owner": "RevOps", "prefix": "PRC", "fallbackCode": "PRC-3", "personas": ["ops", "sales"]},
    {"key": "unsupported-claim", "severity": "High", "title": "Unsupported compliance claim in customer-facing material", "description": "A security claim in buyer-facing material lacks a linked source control and may not be defensible.", "businessImpact": "Regulatory and reputational risk if the claim is challenged in review.", "recommendedFix": "Attach a source citation to each claim or remove unsupported statements.", "owner": "Compliance", "prefix": "SEC", "fallbackCode": "SEC-4.2", "personas": ["compliance", "sales"]},
    {"key": "api-limits", "severity": "Medium", "title": "API rate limits missing from deployment design", "description": "The reference design does not account for the documented default rate limit, risking throttling under load.", "businessImpact": "Throttling in production can degrade customer-facing performance.", "recommendedFix": "Incorporate the documented rate limits and backoff into the design.", "owner": "Platform Eng", "prefix": "API", "fallbackCode": "API-RL", "personas": ["architect", "ops"]},
    {"key": "untested-rollback", "severity": "Medium", "title": "Rollback not verified before migration window", "description": "The deployment guide requires tested rollback, but the migration plan has no rollback validation step.", "businessImpact": "An untested rollback can turn a routine change into an outage.", "recommendedFix": "Add a rollback rehearsal to the migration checklist.", "owner": "SRE On-call", "prefix": "DEP", "fallbackCode": "DEP-11", "personas": ["ops", "architect", "field"]},
]


def _evidence_for(sections: List[Dict[str, Any]], prefix: str, fallback: str) -> str:
    for s in sections:
        if s["citationId"].startswith(prefix):
            return s["citationId"]
    return fallback


def risk_analyzer(persona_key: str, market: str, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    available_prefixes = {s["citationId"].split("-")[0] for s in sections}
    high_compliance = market in HIGH_COMPLIANCE_MARKETS or market == "EMEA"

    scored: List[Dict[str, Any]] = []
    for r in _RISK_POOL:
        score = 0
        if r["prefix"] in available_prefixes:
            score += 3
        if persona_key in r["personas"]:
            score += 2
        if r["key"] == "residency" and high_compliance:
            score += 2
        if score > 0:
            scored.append({"r": r, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)

    chosen = [x["r"] for x in scored[:5]]
    if len(chosen) < 3:
        for r in _RISK_POOL:
            if len(chosen) >= 3:
                break
            if r not in chosen:
                chosen.append(r)

    risks: List[Dict[str, Any]] = []
    for r in chosen:
        severity = "High" if (r["key"] == "residency" and high_compliance) else r["severity"]
        risks.append(
            {
                "severity": severity,
                "title": r["title"],
                "description": r["description"],
                "businessImpact": r["businessImpact"],
                "evidenceCode": _evidence_for(sections, r["prefix"], r["fallbackCode"]),
                "recommendedFix": r["recommendedFix"],
                "owner": r["owner"],
            }
        )

    if not any(x["severity"] == "High" for x in risks) and risks:
        risks[0]["severity"] = "High"
    if not any(x["severity"] == "Medium" for x in risks) and len(risks) > 1:
        risks[-1]["severity"] = "Medium"

    return risks[:5]
