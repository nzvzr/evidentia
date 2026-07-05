"""Deterministic risk-signal tools that surface grounded evidence sections."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

Section = Dict[str, Any]


def _matches(section: Section, keywords: List[str]) -> bool:
    hay = f"{section['sectionTitle']} {section['excerpt']}".lower()
    return any(k in hay for k in keywords)


def find_residency_risks(sections: List[Section], market: Optional[str] = None) -> List[Section]:
    keywords = ["residency", "region", "in-region", "sovereign", "us-east-1", "metadata", "processed"]
    return [s for s in sections if _matches(s, keywords)]


def find_sla_risks(sections: List[Section]) -> List[Section]:
    keywords = ["sla", "availability", "uptime", "credit", "outage", "multi-region"]
    return [s for s in sections if _matches(s, keywords)]


def find_api_risks(sections: List[Section]) -> List[Section]:
    keywords = ["api", "rate limit", "requests per minute", "token", "webhook", "backoff"]
    return [s for s in sections if _matches(s, keywords)]


def find_incident_escalation_risks(sections: List[Section]) -> List[Section]:
    keywords = ["incident", "severity", "escalat", "on-call", "pagertree", "deprecated", "page"]
    return [s for s in sections if _matches(s, keywords)]
