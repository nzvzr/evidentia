"""Citation grounding tools.

Deterministic, explainable relevance scoring for repairing invalid evidence
codes. No LLM, no embeddings — an IDF-weighted lexical scorer with generic-term
downweighting, exact multi-word phrase bonuses, and a minimum-relevance gate.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Tuple

Section = Dict[str, Any]

# Sentinel used when an item genuinely has no grounded evidence. It is NOT
# counted as an invented/ungrounded code — it is an honest "insufficient
# evidence" marker produced by the grounding-repair stage.
INSUFFICIENT_EVIDENCE = "N/A"

# Function words removed before matching.
_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "our",
    "before", "after", "across", "within", "their", "must", "should", "using",
    "based", "against", "each", "when", "have", "has", "are", "was", "will",
    "not", "any", "per", "via", "its", "than", "then", "them", "they",
}

# Content words that are too generic to signal real relevance. Downweighted
# heavily and never counted as "meaningful" matches.
GENERIC_TERMS = {
    "data", "customer", "customers", "system", "systems", "process", "processes",
    "support", "service", "services", "document", "documents", "documentation",
    "information", "review", "reviews", "team", "teams", "report", "reports",
}

_GENERIC_WEIGHT = 0.15
_TITLE_WEIGHT = 2.0
_EXCERPT_WEIGHT = 1.0
_PHRASE_BONUS = 3.0

# Item fields that carry meaning for relevance scoring.
_ITEM_FIELDS = ("title", "description", "businessImpact", "recommendedFix", "whyItMatters", "expectedOutput")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", " ", (text or "").lower()).strip()


def _words(text: str) -> List[str]:
    return [w for w in _norm(text).split() if w]


def _tokens(text: str) -> List[str]:
    return [w for w in _words(text) if len(w) >= 3 and w not in _STOP]


def get_sections_by_citation_ids(sections: List[Section], citation_ids: List[str]) -> List[Section]:
    wanted = set(citation_ids)
    return [s for s in sections if s["citationId"] in wanted]


def validate_citation_ids(sections: List[Section], citation_ids: List[str]) -> List[str]:
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
    Empty strings and the INSUFFICIENT_EVIDENCE sentinel are not counted."""
    return sum(1 for c in codes if c and c != INSUFFICIENT_EVIDENCE and c not in available)


# --------------------------------------------------------------------------- #
# relevance scoring
# --------------------------------------------------------------------------- #

def build_idf(sections: List[Section]) -> Dict[str, float]:
    """Inverse-document-frequency over section (title + excerpt) tokens.
    Rare/domain terms get high weight; corpus-common terms get low weight."""
    n = len(sections) or 1
    df: Dict[str, int] = {}
    for s in sections:
        for t in set(_tokens(f"{s['sectionTitle']} {s['excerpt']}")):
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n + 1) / (dfi + 1)) + 1.0 for t, dfi in df.items()}


def _item_profile(item: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join(item.get(f, "") or "" for f in _ITEM_FIELDS)
    words = _words(text)
    tokens = {w for w in words if len(w) >= 3 and w not in _STOP}
    # candidate 3- then 2-grams with >=2 meaningful words
    phrases: List[str] = []
    seen: set[str] = set()
    for n in (3, 2):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            meaningful = sum(1 for w in gram if len(w) >= 3 and w not in _STOP and w not in GENERIC_TERMS)
            if meaningful >= 2:
                phrase = " ".join(gram)
                if phrase not in seen:
                    seen.add(phrase)
                    phrases.append(phrase)
    return {"tokens": tokens, "phrases": phrases}


def score_section(profile: Dict[str, Any], section: Section, idf: Dict[str, float]) -> Dict[str, Any]:
    title_tokens = set(_tokens(section["sectionTitle"]))
    excerpt_tokens = set(_tokens(section["excerpt"]))
    section_tokens = title_tokens | excerpt_tokens

    term_score = 0.0
    meaningful: List[str] = []
    for t in profile["tokens"] & section_tokens:
        loc = _TITLE_WEIGHT if t in title_tokens else _EXCERPT_WEIGHT
        if t in GENERIC_TERMS:
            term_score += _GENERIC_WEIGHT * loc
        else:
            term_score += idf.get(t, 1.0) * loc
            meaningful.append(t)

    title_norm = _norm(section["sectionTitle"])
    excerpt_norm = _norm(section["excerpt"])
    phrase_score = 0.0
    matched_phrases: List[str] = []
    strong_phrase = False
    for phrase in profile["phrases"]:
        if phrase in title_norm:
            loc = _TITLE_WEIGHT
        elif phrase in excerpt_norm:
            loc = _EXCERPT_WEIGHT
        else:
            continue
        n_words = len(phrase.split())
        phrase_score += _PHRASE_BONUS * (n_words - 1) * loc
        matched_phrases.append(phrase)
        strong_phrase = True  # candidate phrases already require >=2 meaningful words

    return {
        "citationId": section["citationId"],
        "score": round(term_score + phrase_score, 3),
        "matchedTerms": sorted(meaningful),
        "matchedPhrases": sorted(matched_phrases),
        "meaningfulTermCount": len(meaningful),
        "strongPhrase": strong_phrase,
    }


def choose_repair(
    item: Dict[str, Any],
    sections: List[Section],
    idf: Dict[str, float],
    min_relevance: float,
    min_terms: int = 2,
) -> Tuple[str, Dict[str, Any] | None, List[Dict[str, Any]]]:
    """Return (citation_id_or_sentinel, chosen_detail_or_None, top3_candidates)."""
    profile = _item_profile(item)
    details = [score_section(profile, s, idf) for s in sections]
    details.sort(key=lambda d: (-d["score"], d["citationId"]))
    top3 = [
        {"citationId": d["citationId"], "score": d["score"], "matchedTerms": d["matchedTerms"]}
        for d in details[:3]
    ]
    for d in details:
        qualifies = d["strongPhrase"] or (d["meaningfulTermCount"] >= min_terms and d["score"] >= min_relevance)
        if qualifies:
            return d["citationId"], d, top3
    return INSUFFICIENT_EVIDENCE, None, top3


def repair_grounding(
    workflow_steps: List[Dict[str, Any]],
    risks: List[Dict[str, Any]],
    sections: List[Section],
    min_relevance: float = 2.0,
    min_terms: int = 2,
) -> Dict[str, Any]:
    """Validate and repair evidence codes in place using the relevance scorer.

    Invalid codes are replaced with the most relevant valid citation that clears
    the threshold; otherwise the item is marked INSUFFICIENT_EVIDENCE (never the
    least-bad citation). Returns before/after ungrounded counts, repair count,
    and a per-item audit trail.
    """
    available = {s["citationId"] for s in sections}
    idf = build_idf(sections)
    items = [("workflow", w) for w in workflow_steps] + [("risk", r) for r in risks]
    before = count_ungrounded([i.get("evidenceCode", "") for _t, i in items], available)

    repairs = 0
    audit: List[Dict[str, Any]] = []
    for item_type, item in items:
        code = item.get("evidenceCode", "")
        if not code or code == INSUFFICIENT_EVIDENCE or code in available:
            continue
        chosen, detail, top3 = choose_repair(item, sections, idf, min_relevance, min_terms)
        item["evidenceCode"] = chosen
        replaced = chosen != INSUFFICIENT_EVIDENCE
        if replaced:
            repairs += 1
        audit.append({
            "itemType": item_type,
            "itemTitle": item.get("title", ""),
            "originalEvidenceCode": code,
            "replacementEvidenceCode": chosen,
            "relevanceScore": detail["score"] if detail else 0.0,
            "matchedTerms": detail["matchedTerms"] if detail else [],
            "matchedPhrases": detail["matchedPhrases"] if detail else [],
            "repairDecision": "replaced" if replaced else "insufficient-evidence",
            "candidateCitationScores": top3,
        })

    after = count_ungrounded([i.get("evidenceCode", "") for _t, i in items], available)
    return {"before": before, "after": after, "repairs": repairs, "audit": audit}
