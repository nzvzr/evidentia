"""Auto intensity router.

Selects off / summary / full from deterministic-baseline signals so the LLM is
only used where it adds value. Pure and deterministic for easy unit testing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RoutingSignals:
    document_complexity: int          # number of selected documents
    contradictions: int               # documented conflicts/gaps in the corpus
    citation_coverage: float          # 0-100 (metrics.citationCoverage)
    persona_complexity: int           # 1 for custom/free-text roles, else 0
    deterministic_confidence: int     # 0-100 (metrics.confidence)


def route_intensity(signals: RoutingSignals) -> str:
    """Return 'off' | 'summary' | 'full'.

    - Insufficient evidence (<=1 doc): cheap summary polish only — full won't help
      without evidence.
    - Hard cases (contradictions, custom persona, large corpus, or low
      deterministic confidence): full multi-agent refinement.
    - Simple, well-covered, high-confidence cases: off (deterministic is enough).
    - Everything else: summary.
    """
    if signals.document_complexity <= 1:
        return "summary"

    if (
        signals.contradictions >= 1
        or signals.persona_complexity >= 1
        or signals.document_complexity >= 6
        or signals.deterministic_confidence < 84
    ):
        return "full"

    if (
        signals.deterministic_confidence >= 92
        and signals.citation_coverage >= 90
        and signals.contradictions == 0
        and signals.persona_complexity == 0
    ):
        return "off"

    return "summary"
