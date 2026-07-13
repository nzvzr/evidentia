"""Risk Analyzer — evidence-first, source-constrained risk generation.

A risk is only emitted as grounded when a *selected* source section from its
own document contains sufficient risk-specific signals. Unsupported risks are
dropped (never force-filled to a count). When too few grounded risks exist and
the missing documentation is itself operationally relevant, a single explicit
evidence-gap risk may be emitted. Internal provenance is returned separately and
never placed in the public report.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.tools.citation_tools import INSUFFICIENT_EVIDENCE
from app.tools.evidence_support import best_supporting_section, market_is_regulated

# Risk templates carry both the human text and the evidence contract used to
# ground them (source document, required signals/phrases, category, personas).
RISK_TEMPLATES: List[Dict[str, Any]] = [
    {
        "key": "residency", "severity": "High",
        "title": "Data residency gap for EMEA deployments",
        "description": "Default control-plane routing stores metadata in us-east-1; regulated markets require in-region processing that is not enabled by default.",
        "businessImpact": "Blocks compliant onboarding; regulatory and deal exposure.",
        "recommendedFix": "Enable in-region processing and change default routing before regional GA.",
        "owner": "Platform Eng",
        "sourceDocId": "data-residency-sovereignty-policy", "category": "Compliance",
        "signals": ["residency", "us-east-1", "in-region", "metadata", "sovereign", "regulated", "processed"],
        "phrases": ["in-region processing", "control-plane metadata"],
        "personas": ["compliance", "architect", "sales"], "marketSensitive": True,
        "resolvedIf": ["in-region processing is enabled by default", "residency is fully compliant"],
    },
    {
        "key": "sla-multiregion", "severity": "Medium",
        "title": "SLA credit terms undefined for multi-region outages",
        "description": "The SLA specifies single-region remedies but is silent on simultaneous multi-region failure.",
        "businessImpact": "Ambiguous remedy in a correlated outage; credit disputes.",
        "recommendedFix": "Define multi-region credit terms and legal-review the SLA addendum.",
        "owner": "Legal / RevOps",
        "sourceDocId": "sla-uptime-commitment", "category": "Reliability",
        "signals": ["sla", "credit", "credits", "availability", "outage", "exclusions", "remedies", "claim"],
        "phrases": ["service credits"],
        "personas": ["ops", "support", "sales", "compliance"], "marketSensitive": False,
        "resolvedIf": ["multi-region credit terms are defined"],
    },
    {
        "key": "incident-tool", "severity": "Medium",
        "title": "Incident runbook references a deprecated on-call tool",
        "description": "The escalation section names PagerTree, which was retired — pages may not deliver.",
        "businessImpact": "Sev-1 pages may not deliver, extending time-to-restore.",
        "recommendedFix": "Replace tool references and re-test the escalation path.",
        "owner": "SRE On-call",
        "sourceDocId": "incident-response-runbook", "category": "Operations",
        "signals": ["pagertree", "deprecated", "escalation", "escalate", "on-call", "paging", "severity"],
        "phrases": ["on-call routing", "deprecated and must be replaced"],
        "personas": ["ops", "support", "field", "newhire"], "marketSensitive": False,
        "resolvedIf": ["pagertree has been removed from the runbook"],
    },
    {
        "key": "pricing-egress", "severity": "Low",
        "title": "Pricing sheet omits egress overage tiers",
        "description": "No documented rate for data egress beyond the included allowance; finance review flagged this.",
        "businessImpact": "Unforecastable egress cost for customers and finance.",
        "recommendedFix": "Publish egress overage tiers in the pricing sheet.",
        "owner": "RevOps",
        "sourceDocId": "pricing-packaging-sheet", "category": "Pricing",
        "signals": ["egress", "overage", "tiers", "allowance", "pricing", "finance"],
        "phrases": ["egress overage"],
        "personas": ["ops", "sales"], "marketSensitive": False,
        "resolvedIf": ["egress overage tiers are published"],
    },
    {
        "key": "unsupported-claim", "severity": "High",
        "title": "Unsupported compliance claim in customer-facing material",
        "description": "A security claim in buyer-facing material lacks a linked source control and may not be defensible.",
        "businessImpact": "Regulatory and reputational risk if the claim is challenged in review.",
        "recommendedFix": "Attach a source citation to each claim or remove unsupported statements.",
        "owner": "Compliance",
        "sourceDocId": "security-compliance-whitepaper", "category": "Security",
        "signals": ["security", "encryption", "encrypted", "control", "controls", "audit", "compliance", "certification"],
        "phrases": ["access control", "encrypted at rest"],
        "personas": ["compliance", "sales"], "marketSensitive": True,
        "resolvedIf": [],
    },
    {
        "key": "api-limits", "severity": "Medium",
        "title": "API rate limits missing from deployment design",
        "description": "The reference design does not account for the documented default rate limit, risking throttling under load.",
        "businessImpact": "Throttling in production can degrade customer-facing performance.",
        "recommendedFix": "Incorporate the documented rate limits and backoff into the design.",
        "owner": "Platform Eng",
        "sourceDocId": "platform-api-reference", "category": "API",
        "signals": ["api", "rate", "limit", "limits", "requests", "throttle", "backoff", "token", "webhook"],
        "phrases": ["rate limit", "requests per minute"],
        "personas": ["architect", "ops"], "marketSensitive": False,
        "resolvedIf": [],
    },
    {
        "key": "untested-rollback", "severity": "Medium",
        "title": "Rollback not verified before migration window",
        "description": "The deployment guide requires tested rollback, but the migration plan has no rollback validation step.",
        "businessImpact": "An untested rollback can turn a routine change into an outage.",
        "recommendedFix": "Add a rollback rehearsal to the migration checklist.",
        "owner": "SRE On-call",
        "sourceDocId": "deployment-migration-guide", "category": "Deployment",
        "signals": ["rollback", "migration", "deployment", "failover", "topology", "replication", "blue-green"],
        "phrases": ["automated rollback", "blue-green"],
        "personas": ["ops", "architect", "field"], "marketSensitive": False,
        "resolvedIf": [],
    },
]

_SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}

# Persona → source-document categories whose absence makes an evidence gap
# operationally relevant enough to report explicitly.
_CRITICAL_CATEGORIES = {
    "compliance": {"Compliance", "Security"},
    "architect": {"Deployment", "API"},
    "ops": {"Reliability", "Operations"},
    "sales": {"Security", "Compliance"},
    "support": {"Operations", "Reliability"},
    "field": {"Operations", "Deployment"},
    "newhire": {"Operations", "Enablement"},
}


def _clean_risk(template: Dict[str, Any], citation_id: str, high_compliance: bool) -> Dict[str, Any]:
    severity = "High" if (template["key"] == "residency" and high_compliance) else template["severity"]
    return {
        "severity": severity,
        "title": template["title"],
        "description": template["description"],
        "businessImpact": template["businessImpact"],
        "evidenceCode": citation_id,
        "recommendedFix": template["recommendedFix"],
        "owner": template["owner"],
    }


def risk_analyzer(
    persona_key: str,
    market: str,
    sections: List[Dict[str, Any]],
    min_support: int = 2,
    max_risks: int = 5,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    high_compliance = market_is_regulated(market)
    selected_categories = {s.get("category") for s in sections}

    # 1) propose the risks this persona/market would consider
    proposed = [
        t for t in RISK_TEMPLATES
        if persona_key in t["personas"] or (t.get("marketSensitive") and high_compliance)
    ]

    kept: List[Dict[str, Any]] = []          # (template, detail)
    audit: List[Dict[str, Any]] = []
    dropped = 0
    source_mismatch = 0

    for t in proposed:
        detail = best_supporting_section(t, sections, persona_key, market)
        if detail is None:
            source_mismatch += 1
            dropped += 1
            audit.append(_audit(t, None, 0.0, "source-document-not-selected", "dropped"))
            continue
        if detail["negated"]:
            dropped += 1
            audit.append(_audit(t, detail, detail["score"], "evidence-contradicts-claim", "dropped"))
            continue
        if detail["owns"] and detail["strength"] >= min_support:
            kept.append((t, detail))
        else:
            dropped += 1
            audit.append(_audit(t, detail, detail["score"], "insufficient-signal-support", "dropped"))

    # 2) rank grounded risks; never invent filler to hit a count
    kept.sort(key=lambda kd: (
        0 if persona_key in kd[0]["personas"] else 1,
        -kd[1]["score"],
        _SEVERITY_ORDER.get(kd[0]["severity"], 3),
    ))
    if len(kept) > max_risks:
        for t, d in kept[max_risks:]:
            audit.append(_audit(t, d, d["score"], "exceeds-max-risks", "dropped"))
        kept = kept[:max_risks]

    risks: List[Dict[str, Any]] = []
    provenance: List[Dict[str, Any]] = []
    support_scores: List[float] = []
    for t, d in kept:
        risks.append(_clean_risk(t, d["citationId"], high_compliance))
        support_scores.append(d["score"])
        provenance.append({
            "sourceDocumentId": d["documentId"],
            "sourceCitationId": d["citationId"],
            "matchedSignals": d["matchedSignals"],
            "generationReason": "evidence-derived",
            "supportScore": d["score"],
        })

    # 3) explicit evidence-gap risk only when the missing docs are operationally relevant
    insufficient_emitted = 0
    if len(risks) < 2 and persona_key in _CRITICAL_CATEGORIES:
        missing = sorted(_CRITICAL_CATEGORIES[persona_key] - {c for c in selected_categories if c})
        if missing:
            risks.append({
                "severity": "Medium",
                "title": "Insufficient documentation to assess key risks",
                "description": f"The selected corpus lacks {', '.join(missing)} documentation, so material {persona_key} risks cannot be grounded in evidence.",
                "businessImpact": "Ungrounded risk posture; decisions may miss material exposure.",
                "evidenceCode": INSUFFICIENT_EVIDENCE,
                "recommendedFix": f"Add {', '.join(missing)} documents to the workspace and re-run.",
                "owner": "Compliance",
            })
            provenance.append({
                "sourceDocumentId": None, "sourceCitationId": INSUFFICIENT_EVIDENCE,
                "matchedSignals": [], "generationReason": "evidence-gap", "supportScore": 0.0,
            })
            insufficient_emitted = 1
            audit.append({
                "itemType": "risk", "title": "Insufficient documentation to assess key risks",
                "proposedRiskOrStep": "evidence-gap", "proposedSourceDocumentId": None,
                "proposedCitationId": INSUFFICIENT_EVIDENCE, "supportScore": 0.0,
                "rejectionReason": f"missing:{','.join(missing)}", "finalDecision": "evidence-gap",
            })

    gen_info = {
        "generatedBeforeFiltering": len(proposed),
        "groundedKept": len(support_scores),
        "unsupportedDropped": dropped,
        "insufficientEmitted": insufficient_emitted,
        "sourceDocumentMismatch": source_mismatch,
        "supportScores": support_scores,
        "provenance": provenance,
        "audit": audit,
    }
    return risks, gen_info


def _audit(template, detail, score, reason, decision) -> Dict[str, Any]:
    return {
        "itemType": "risk",
        "title": template["title"],
        "proposedRiskOrStep": template["key"],
        "proposedSourceDocumentId": template["sourceDocId"],
        "proposedCitationId": detail["citationId"] if detail else None,
        "supportScore": round(score, 3),
        "rejectionReason": reason,
        "finalDecision": decision,
    }
