"""Deterministic evidence-support scorer.

Assesses whether a selected source section actually supports a specific risk or
workflow claim — distinct from citation *repair* (which only checks code
validity). No LLM, no embeddings. Explainable: returns matched signals, phrases,
ownership, and negation flags.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.tools.scoring_tools import HIGH_COMPLIANCE_MARKETS

Section = Dict[str, Any]

_OWNERSHIP_WEIGHT = 3.0
_SIGNAL_WEIGHT = 1.0
_PHRASE_WEIGHT = 2.0
_PERSONA_WEIGHT = 1.0
_MARKET_WEIGHT = 1.0
_CATEGORY_WEIGHT = 1.0
_NEGATION_PENALTY = 4.0

_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "must", "should", "your", "our"}


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9-]+", (text or "").lower()) if len(t) >= 3 and t not in _STOP}


def market_is_regulated(market: str) -> bool:
    return market in HIGH_COMPLIANCE_MARKETS or market == "EMEA"


def _section_text(section: Section) -> str:
    return f"{section['sectionTitle']} {section['excerpt']}".lower()


def score_support(claim: Dict[str, Any], section: Section, persona_key: str, market: str) -> Dict[str, Any]:
    """Score how well `section` supports the `claim` template.

    `claim` provides: sourceDocId, signals[], phrases[], personas[], category,
    marketSensitive, resolvedIf[] (contradiction markers).
    """
    text = _section_text(section)
    matched_signals = sorted({s for s in claim.get("signals", []) if s in text})
    matched_phrases = sorted({p for p in claim.get("phrases", []) if p in text})
    owns = section.get("documentId") == claim.get("sourceDocId")
    negated = any(neg in text for neg in claim.get("resolvedIf", []))
    category_affinity = bool(claim.get("category")) and section.get("category") == claim.get("category")
    persona_relevant = persona_key in claim.get("personas", [])
    market_relevant = bool(claim.get("marketSensitive")) and market_is_regulated(market)

    score = 0.0
    score += _OWNERSHIP_WEIGHT if owns else 0.0
    score += _SIGNAL_WEIGHT * len(matched_signals)
    score += _PHRASE_WEIGHT * len(matched_phrases)
    score += _PERSONA_WEIGHT if persona_relevant else 0.0
    score += _MARKET_WEIGHT if market_relevant else 0.0
    score += _CATEGORY_WEIGHT if category_affinity else 0.0
    if negated:
        score -= _NEGATION_PENALTY

    # signal strength gates grounding: enough claim-specific evidence in the section.
    strength = len(matched_signals) + 2 * len(matched_phrases)

    return {
        "citationId": section["citationId"],
        "documentId": section.get("documentId"),
        "score": round(score, 3),
        "strength": strength,
        "owns": owns,
        "negated": negated,
        "matchedSignals": matched_signals + matched_phrases,
        "matchedSignalTerms": matched_signals,
        "matchedPhrases": matched_phrases,
    }


def best_supporting_section(
    claim: Dict[str, Any], sections: List[Section], persona_key: str, market: str
) -> Dict[str, Any] | None:
    """Return the highest-scoring section OWNED by the claim's source document."""
    owned = [s for s in sections if s.get("documentId") == claim.get("sourceDocId")]
    if not owned:
        return None
    scored = [score_support(claim, s, persona_key, market) for s in owned]
    scored.sort(key=lambda d: (-d["score"], d["citationId"]))
    return scored[0]
