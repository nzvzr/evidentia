"""Lightweight output-quality validation for LLM text.

Rejects vague, overlong, corrupted, or repetitive text so the deterministic
baseline can be kept for that field instead.
"""

from __future__ import annotations

import re
from typing import List, Optional

VAGUE_PHRASES = [
    "critical insights",
    "actionable recommendations",
    "actionable insights",
    "operational readiness",
    "business value",
    "leverage documentation",
    "leverage the documentation",
    "drive business value",
    "optimize processes",
    "optimise processes",
    "enhance operational",
    "unlock value",
    "synergy",
    "holistic approach",
    "best-in-class",
    "cutting-edge",
    "seamless experience",
    "empower your team",
]


def _has_corrupted_words(text: str) -> bool:
    for token in re.findall(r"[A-Za-z]{9,}", text):
        # A long alphabetic run with no vowels is almost certainly corrupted.
        if not re.search(r"[aeiouAEIOU]", token):
            return True
    # Excessive repeated characters (e.g. "aaaaaa").
    if re.search(r"(.)\1{4,}", text):
        return True
    return False


def _too_repetitive(text: str) -> bool:
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if len(sentences) < 3:
        return False
    starts = [" ".join(s.split()[:3]).lower() for s in sentences]
    # If more than half the sentences share the same 3-word opening, reject.
    most_common = max((starts.count(s) for s in set(starts)), default=0)
    return most_common > len(sentences) / 2


def is_precise_text(
    text: str,
    max_len: int = 600,
    require_terms: Optional[List[str]] = None,
) -> bool:
    if not text or not text.strip():
        return False
    if len(text) > max_len:
        return False
    low = text.lower()
    if any(p in low for p in VAGUE_PHRASES):
        return False
    if _has_corrupted_words(text):
        return False
    if _too_repetitive(text):
        return False
    if require_terms and not any(t.lower() in low for t in require_terms):
        return False
    return True
