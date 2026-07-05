"""Citation grounding tools — ensure agents only use real citation ids."""

from __future__ import annotations

from typing import Any, Dict, List

Section = Dict[str, Any]


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
