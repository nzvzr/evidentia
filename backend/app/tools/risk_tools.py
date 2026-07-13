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


# Contradiction / documented-gap patterns: a pattern fires when BOTH keyword
# groups appear anywhere in the selected corpus, indicating conflicting or
# internally inconsistent guidance the reader must reconcile.
_CONTRADICTION_PATTERNS = [
    (["us-east-1"], ["in-region", "regulated", "sovereign"]),          # residency default vs in-region need
    (["deprecated", "pagertree"], ["escalat", "on-call", "severity 1"]),  # deprecated tool in live escalation
    (["service credits", "credit"], ["multi-region", "exclusions"]),   # credit ambiguity across regions
]


def detect_contradictions(sections: List[Section], market: Optional[str] = None) -> int:
    """Count documented contradictions/gaps across the selected sections."""
    corpus = " ".join(f"{s['sectionTitle']} {s['excerpt']}".lower() for s in sections)
    count = 0
    for group_a, group_b in _CONTRADICTION_PATTERNS:
        if any(a in corpus for a in group_a) and any(b in corpus for b in group_b):
            count += 1
    return count
