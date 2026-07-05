"""Citation Binder agent — binds workflow/risk evidence to real source sections."""

from __future__ import annotations

from typing import Any, Dict, List

_WHY_BY_ID = {
    "SEC-4.2": "Anchors every security-posture claim to a verifiable control statement.",
    "RES-14": "Establishes the residency default that drives the top finding and highest-severity risk.",
    "SLA-3": "Sets the availability target the recommended failover design must satisfy.",
    "INC-2.1": "Defines escalation timing and surfaces the deprecated-tool risk.",
    "DEP-11": "Backs the deployment-topology and rollback recommendations.",
    "API-RL": "Bounds the rate limits any reference architecture must respect.",
    "PRC-3": "Documents the pricing gap behind the egress-overage risk.",
}


def _why(section: Dict[str, Any]) -> str:
    return _WHY_BY_ID.get(
        section["citationId"],
        f"Backs the {section['sectionTitle'].lower()} guidance drawn from the {section['source']}.",
    )


def citation_binder(
    sections: List[Dict[str, Any]],
    workflow_steps: List[Dict[str, Any]],
    risks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for s in sections:
        by_id.setdefault(s["citationId"], s)

    referenced: List[str] = []

    def push(cid: str) -> None:
        if cid and cid in by_id and cid not in referenced:
            referenced.append(cid)

    for w in workflow_steps:
        push(w["evidenceCode"])
    for r in risks:
        push(r["evidenceCode"])

    target = min(8, max(6, len(sections)))
    for s in sections:
        if len(referenced) >= target:
            break
        push(s["citationId"])

    citations: List[Dict[str, Any]] = []
    for cid in referenced:
        s = by_id[cid]
        citations.append(
            {
                "id": s["citationId"],
                "source": f"{s['source']} · {s['sectionTitle']}",
                "section": s["sectionTitle"],
                "excerpt": s["excerpt"],
                "whyItMatters": _why(s),
            }
        )
    return citations
