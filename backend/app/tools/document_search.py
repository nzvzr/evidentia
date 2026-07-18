"""Deterministic document-search tools used by the agents."""

from __future__ import annotations

import re
from typing import Any, Dict, List

Section = Dict[str, Any]

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are",
    "with", "by", "be", "as", "at", "must", "should", "this", "that",
}


def _tokens(text: str) -> List[str]:
    words = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower()).split()
    return [w for w in words if len(w) > 2 and w not in _STOP]


def _overlap(haystack: str, needles: List[str]) -> int:
    hay = set(_tokens(haystack))
    return sum(1 for n in needles if n in hay)


def search_document_sections(sections: List[Section], query: str, limit: int = 6) -> List[Section]:
    needles = _tokens(query)
    if not needles:
        return sections[:limit]
    scored = sorted(
        sections,
        key=lambda s: _overlap(
            f"{s['sectionTitle']} {s.get('text', s['excerpt'])}", needles
        ),
        reverse=True,
    )
    return scored[:limit]


def rank_sections_for_persona(sections: List[Section], persona: Dict[str, Any], market: str) -> List[Section]:
    needles = _tokens(
        " ".join(
            persona.get("relevantTopics", [])
            + persona.get("priorities", [])
            + persona.get("riskFocus", [])
            + [market or ""]
        )
    )
    return sorted(
        sections,
        key=lambda s: _overlap(
            f"{s['sectionTitle']} {s.get('text', s['excerpt'])} {s['category']}", needles
        ),
        reverse=True,
    )


def summarize_sections(sections: List[Section], max_chars: int = 2400) -> str:
    lines: List[str] = []
    used = 0
    for s in sections:
        line = f"[{s['citationId']}] {s['source']} — {s['sectionTitle']}: {s['excerpt']}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
