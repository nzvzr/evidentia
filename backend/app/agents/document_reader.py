"""Document Reader / Ingest agent.

Loads selected demo markdown files, splits them into `## ` sections, and attaches
a source-traceable citation id to each section (aligned to document metadata).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "documents"

DOCUMENTS: List[Dict[str, Any]] = [
    {
        "id": "security-compliance-whitepaper",
        "title": "Security & Compliance Whitepaper",
        "short": "Security Whitepaper",
        "type": "Security",
        "category": "Security",
        "extent": "48 pages",
        "lastUpdated": "Jun 22 2026",
        "format": "PDF",
        "citationPrefix": "SEC",
        "citationIds": ["SEC-4.2", "SEC-5.1", "SEC-6.3", "SEC-8.2"],
        "usedByPersonas": ["Sales Engineer", "Compliance Officer", "Solutions Architect"],
        "topics": ["Encryption", "Access control", "Audit", "Certifications"],
    },
    {
        "id": "platform-api-reference",
        "title": "Platform API Reference",
        "short": "API Reference",
        "type": "API",
        "category": "API",
        "extent": "320 endpoints",
        "lastUpdated": "Jul 01 2026",
        "format": "HTML",
        "citationPrefix": "API",
        "citationIds": ["API-RL", "API-2.4", "API-5.0", "API-7.1"],
        "usedByPersonas": ["Solutions Architect", "Sales Engineer"],
        "topics": ["Auth", "Rate limits", "Retries", "Webhooks"],
    },
    {
        "id": "sla-uptime-commitment",
        "title": "SLA & Uptime Commitment",
        "short": "SLA Commitment",
        "type": "Reliability",
        "category": "Reliability",
        "extent": "12 pages",
        "lastUpdated": "May 30 2026",
        "format": "PDF",
        "citationPrefix": "SLA",
        "citationIds": ["SLA-3", "SLA-5", "SLA-2", "SLA-8"],
        "usedByPersonas": ["Support Agent", "Operations Manager", "Sales Engineer"],
        "topics": ["Availability", "Credits", "Exclusions", "Escalation"],
    },
    {
        "id": "deployment-migration-guide",
        "title": "Deployment & Migration Guide",
        "short": "Deployment Guide",
        "type": "Deployment",
        "category": "Deployment",
        "extent": "86 pages",
        "lastUpdated": "Jun 15 2026",
        "format": "PDF",
        "citationPrefix": "DEP",
        "citationIds": ["DEP-11", "DEP-4", "DEP-7", "DEP-2"],
        "usedByPersonas": ["Solutions Architect", "Operations Manager", "New Hire"],
        "topics": ["Topology", "Failover", "Migration", "Rollback"],
    },
    {
        "id": "data-residency-sovereignty-policy",
        "title": "Data Residency & Sovereignty Policy",
        "short": "Residency Policy",
        "type": "Compliance",
        "category": "Compliance",
        "extent": "24 pages",
        "lastUpdated": "Jun 28 2026",
        "format": "PDF",
        "citationPrefix": "RES",
        "citationIds": ["RES-14", "RES-9", "RES-3", "RES-7"],
        "usedByPersonas": ["Compliance Officer", "Solutions Architect", "Sales Engineer"],
        "topics": ["Residency", "Regulated workloads", "Sovereign cloud", "Data export"],
    },
    {
        "id": "incident-response-runbook",
        "title": "Incident Response Runbook",
        "short": "Incident Runbook",
        "type": "Operations",
        "category": "Operations",
        "extent": "31 pages",
        "lastUpdated": "Jun 09 2026",
        "format": "Markdown",
        "citationPrefix": "INC",
        "citationIds": ["INC-2.1", "INC-4.0", "INC-6.2", "INC-9.1"],
        "usedByPersonas": ["Support Agent", "Operations Manager", "New Hire"],
        "topics": ["Severity matrix", "Comms", "Escalation", "On-call"],
    },
    {
        "id": "pricing-packaging-sheet",
        "title": "Pricing & Packaging Sheet",
        "short": "Pricing Sheet",
        "type": "Pricing",
        "category": "Pricing",
        "extent": "5 tabs",
        "lastUpdated": "Jun 18 2026",
        "format": "XLSX",
        "citationPrefix": "PRC",
        "citationIds": ["PRC-3", "PRC-1", "PRC-6", "PRC-4"],
        "usedByPersonas": ["Operations Manager", "Sales Engineer"],
        "topics": ["Tiers", "Usage limits", "Overage", "Discounts"],
    },
    {
        "id": "customer-onboarding-handbook",
        "title": "Customer Onboarding Handbook",
        "short": "Onboarding Handbook",
        "type": "Enablement",
        "category": "Enablement",
        "extent": "40 pages",
        "lastUpdated": "May 24 2026",
        "format": "PDF",
        "citationPrefix": "ONB",
        "citationIds": ["ONB-1", "ONB-3", "ONB-5", "ONB-8"],
        "usedByPersonas": ["New Hire", "Support Agent"],
        "topics": ["Kickoff", "Validation", "Training", "Go-live"],
    },
]

DEFAULT_DOCUMENT_IDS = [
    "security-compliance-whitepaper",
    "sla-uptime-commitment",
    "deployment-migration-guide",
    "customer-onboarding-handbook",
]

_BY_ID = {d["id"]: d for d in DOCUMENTS}


def get_document_meta(doc_id: str) -> Dict[str, Any] | None:
    return _BY_ID.get(doc_id)


def list_documents() -> List[Dict[str, Any]]:
    return DOCUMENTS


def _read_markdown(doc_id: str) -> str:
    path = DOCS_DIR / f"{doc_id}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _parse_sections(markdown: str) -> List[Dict[str, str]]:
    sections: List[Dict[str, str]] = []
    current: Dict[str, Any] | None = None
    for line in markdown.splitlines():
        heading = re.match(r"^##\s+(.*)$", line)
        if heading:
            if current:
                sections.append({"title": current["title"], "excerpt": " ".join(current["body"]).strip()})
            current = {"title": heading.group(1).strip(), "body": []}
        elif current and line.strip() and not line.startswith("#"):
            current["body"].append(line.strip())
    if current:
        sections.append({"title": current["title"], "excerpt": " ".join(current["body"]).strip()})
    return sections


def document_reader(selected_document_ids: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    ids = selected_document_ids or DEFAULT_DOCUMENT_IDS
    documents: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []

    for doc_id in ids:
        meta = get_document_meta(doc_id)
        if not meta:
            continue
        documents.append(meta)
        parsed = _parse_sections(_read_markdown(doc_id))
        for i, s in enumerate(parsed):
            citation_id = meta["citationIds"][i] if i < len(meta["citationIds"]) else f"{meta['citationPrefix']}-{i + 1}"
            sections.append(
                {
                    "documentId": meta["id"],
                    "source": meta["title"],
                    "sectionTitle": s["title"],
                    "excerpt": s["excerpt"],
                    "category": meta["category"],
                    "citationId": citation_id,
                }
            )

    if not documents:
        return document_reader(DEFAULT_DOCUMENT_IDS)
    return documents, sections
