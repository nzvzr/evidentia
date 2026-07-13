"""Citation grounding tools — ensure agents only use real citation ids."""

from __future__ import annotations

import re
from typing import Any, Dict, List

Section = Dict[str, Any]

# Sentinel used when an item genuinely has no grounded evidence. It is NOT
# counted as an invented/ungrounded code — it is an honest "insufficient
# evidence" marker produced by the deterministic grounding-repair stage.
INSUFFICIENT_EVIDENCE = "N/A"

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "our",
    "before", "after", "across", "within", "their", "must", "should", "review",
    "using", "based", "against",
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9-]+", (text or "").lower()) if len(t) > 3 and t not in _STOP}


def get_sections_by_citation_ids(sections: List[Section], citation_ids: List[str]) -> List[Section]:
    wanted = set(citation_ids)
    return [s for s in sections if s["citationId"] in wanted]


def validate_citation_ids(sections: List[Section], citation_ids: List[str]) -> List[str]:
    """Return only the citation ids that actually exist in the sections."""
    valid = {s["citationId"] for s in sections}
    seen: set[str] = set()
    result: List[str] = []
    for cid in citation_ids:
        if cid in valid and cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result


def count_ungrounded(codes: List[str], available: set[str]) -> int:
    """Count evidence codes that are real claims but not in the valid set.

    Empty strings and the INSUFFICIENT_EVIDENCE sentinel are not counted.
    """
    return sum(1 for c in codes if c and c != INSUFFICIENT_EVIDENCE and c not in available)


def _relevant_citation(item: Dict[str, Any], sections: List[Section]) -> str:
    """Pick the most semantically relevant valid citation for an item, or the
    insufficient-evidence sentinel if nothing is relevant."""
    needles = _tokens(f"{item.get('title', '')} {item.get('description', '')} {item.get('businessImpact', '')}")
    best_code = INSUFFICIENT_EVIDENCE
    best_score = 0
    for s in sections:
        score = len(needles & _tokens(f"{s['sectionTitle']} {s['excerpt']}"))
        if score > best_score:
            best_score = score
            best_code = s["citationId"]
    return best_code if best_score > 0 else INSUFFICIENT_EVIDENCE


def repair_grounding(
    workflow_steps: List[Dict[str, Any]],
    risks: List[Dict[str, Any]],
    sections: List[Section],
) -> Dict[str, int]:
    """Deterministically validate and repair evidence codes in place.

    Invalid codes are replaced with a semantically relevant valid citation; if
    none is relevant the item is marked INSUFFICIENT_EVIDENCE rather than keeping
    an invented code. Returns before/after ungrounded counts and repair count.
    """
    available = {s["citationId"] for s in sections}
    items = list(workflow_steps) + list(risks)
    before = count_ungrounded([i.get("evidenceCode", "") for i in items], available)

    repairs = 0
    for item in items:
        code = item.get("evidenceCode", "")
        if code and code != INSUFFICIENT_EVIDENCE and code not in available:
            item["evidenceCode"] = _relevant_citation(item, sections)
            repairs += 1

    after = count_ungrounded([i.get("evidenceCode", "") for i in items], available)
    return {"before": before, "after": after, "repairs": repairs}
