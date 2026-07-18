"""Deterministic section classification engine (M3): ``CLASSIFIER_VERSION``.

Executes domain-module signature packs over the **full bounded section text**
(never only the excerpt). No LLM call, no embeddings, no network, no dynamic
rule execution — pure regex/token scoring over declarative module data, the
exact idiom the codebase already trusts (`evidence_support`,
`citation_tools`). Any instruction-shaped text inside a document is treated
as text only: it can at most trip an *injection flag*, never change engine
behavior.

**The engine never branches on a taxonomy label** (PLATFORM_ARCHITECTURE.md
§3.1): categories, topics, market facets and persona needles are opaque
module data iterated generically; the only category name this module knows
structurally is "whichever the module declares as fallback".

Outputs per section: category (module fallback = the explicit below-threshold
outcome), topics, market flags, persona affinity, keywords, injection flags,
the matched deterministic rule ids, and a canonical **classification
signature** (sha256) proving which engine + module + thresholds produced the
result — no timestamps, no database ids, no transient execution metadata, so
retries reproduce it bit-for-bit.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Pattern, Sequence, Tuple

from app.ingestion.sectionizer import SectionDraft
from app.modules.loader import DomainModule, ModuleValidationError, canonical_json

CLASSIFIER_VERSION = "m3.1"
# The canonical section-signature payload format below ("v" field). Versioned
# with the engine: any change to the payload shape is a new signature version.
SECTION_SIGNATURE_VERSION = 1
# signatures.json pack formats this engine can execute. A pack declaring an
# unknown signatureVersion fails closed before any classification runs.
SUPPORTED_SIGNATURE_PACK_VERSIONS = frozenset({"1.0.0"})


def ensure_module_compatible(module: DomainModule) -> None:
    """Fail closed unless the module pack declares compatibility with THIS
    engine: the pack's engineCompatibility must admit CLASSIFIER_VERSION and
    its signatureVersion must be a supported pack format. Enforced before any
    classification and reflected in the complete finalization target."""
    allowed = module.engine_compatibility.get("classifier")
    if allowed is not None and CLASSIFIER_VERSION not in allowed:
        raise ModuleValidationError(
            f"module {module.module_id}@{module.version} does not support "
            f"classifier {CLASSIFIER_VERSION} (declares {list(allowed)})"
        )
    if module.signature_version not in SUPPORTED_SIGNATURE_PACK_VERSIONS:
        raise ModuleValidationError(
            f"module {module.module_id}@{module.version} declares unsupported "
            f"signatureVersion {module.signature_version!r}"
        )

# --- injection screening (engine security data, versioned with the engine) --- #
# Deterministic signature flags for prompt-injection-shaped content
# (DOCUMENT_INGESTION_ARCHITECTURE.md §12). Flags surface as metadata; the
# text itself is never executed and never alters classification.
_INJECTION_PATTERNS: Tuple[Tuple[str, Pattern[str]], ...] = (
    (
        "instruction-override",
        re.compile(
            r"\b(?:ignore|disregard|forget)\b[^.\n]{0,40}\b(?:previous|prior|above|all)\b"
            r"[^.\n]{0,40}\b(?:instructions?|prompts?|rules?)\b"
        ),
    ),
    (
        "role-marker",
        re.compile(r"(?:^|\n)\s*(?:system|assistant|user)\s*:", re.IGNORECASE),
    ),
    (
        "prompt-reference",
        re.compile(r"\bsystem prompt\b|\byou are now\b|\bact as\b[^.\n]{0,40}\b(?:an?|the)\b"),
    ),
    (
        "jailbreak-vocabulary",
        re.compile(r"\bjailbreak\b|\bdeveloper mode\b|\bdo anything now\b"),
    ),
)

# Keyword extraction vocabulary (engine data, versioned with the engine):
# display/search metadata only — nothing analytical depends on keywords.
_KEYWORD_STOPWORDS = frozenset(
    """
    about above after again all also and any are because been before being below between both
    but can cannot could does doing down during each few for from further has have having her
    here hers him his how into itself just more most not now off once only other our ours out
    over own same shall she should some such than that the their theirs them then there these
    they this those through under until very was were what when where which while who whom why
    will with would you your yours must may might upon within without via per each using use
    used section document documents version team teams
    """.split()
)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]{3,}")
_WS_RE = re.compile(r"\s+")
_MAX_KEYWORDS = 6


def _fold(text: str) -> str:
    return _WS_RE.sub(" ", text.casefold())


def _compile_terms(terms: Sequence[str]) -> Tuple[Tuple[str, Pattern[str]], ...]:
    compiled = []
    for term in terms:
        folded = _fold(term).strip()
        pattern = re.compile(r"(?<![a-z0-9])" + re.escape(folded).replace(r"\ ", r"\s+") + r"(?![a-z0-9])")
        compiled.append((term, pattern))
    return tuple(compiled)


@dataclass(frozen=True)
class _CompiledCategoryRule:
    rule_id: str
    category: str
    heading_signals: Tuple[Tuple[str, Pattern[str]], ...]
    signals: Tuple[Tuple[str, Pattern[str]], ...]
    phrases: Tuple[Tuple[str, Pattern[str]], ...]
    exclusions: Tuple[Tuple[str, Pattern[str]], ...]  # (rule_id, pattern)


@dataclass(frozen=True)
class _CompiledModule:
    module: DomainModule
    categories: Tuple[_CompiledCategoryRule, ...]
    topics: Tuple[Tuple[str, str, Tuple[Tuple[str, Pattern[str]], ...], Tuple[Tuple[str, Pattern[str]], ...]], ...]
    markets: Tuple[Tuple[str, str, Tuple[Tuple[str, Pattern[str]], ...], Tuple[Tuple[str, Pattern[str]], ...]], ...]
    personas: Tuple[Tuple[str, Tuple[Tuple[str, Pattern[str]], ...]], ...]


# Manual cache keyed by the module digest (DomainModule holds dict fields, so
# it is not itself hashable). Modules are immutable within a release, so the
# digest fully identifies the compiled form.
_COMPILED_CACHE: Dict[str, _CompiledModule] = {}


def _compile_module(module: DomainModule) -> _CompiledModule:
    cached = _COMPILED_CACHE.get(module.digest)
    if cached is not None:
        return cached
    compiled = _build_compiled(module)
    if len(_COMPILED_CACHE) > 8:  # bounded: never grows past a handful of packs
        _COMPILED_CACHE.clear()
    _COMPILED_CACHE[module.digest] = compiled
    return compiled


def _build_compiled(module: DomainModule) -> _CompiledModule:
    return _CompiledModule(
        module=module,
        categories=tuple(
            _CompiledCategoryRule(
                rule_id=rule.rule_id,
                category=rule.category,
                heading_signals=_compile_terms(rule.heading_signals),
                signals=_compile_terms(rule.signals),
                phrases=_compile_terms(rule.phrases),
                exclusions=tuple(
                    (excl.rule_id, _compile_terms([excl.phrase])[0][1]) for excl in rule.exclusions
                ),
            )
            for rule in module.category_rules
        ),
        topics=tuple(
            (t.rule_id, t.label, _compile_terms(t.signals), _compile_terms(t.phrases))
            for t in module.topic_rules
        ),
        markets=tuple(
            (m.rule_id, m.market, _compile_terms(m.signals), _compile_terms(m.phrases))
            for m in module.market_rules
        ),
        personas=tuple(
            (p.persona_id, _compile_terms(p.needles)) for p in module.personas
        ),
    )


@dataclass
class SectionClassification:
    """The deterministic classification result for one section."""

    category: str
    topics: List[str]
    market_flags: List[str]
    persona_affinity: Dict[str, float]
    keywords: List[str]
    injection_flags: List[str]
    matched_rules: List[str]
    signature: str  # sha256 hex; canonical, retry-stable

    classifier_version: str = CLASSIFIER_VERSION


def _count_hits(compiled: Sequence[Tuple[str, Pattern[str]]], text: str) -> List[str]:
    return [term for term, pattern in compiled if pattern.search(text)]


def classification_heading_input(draft: SectionDraft) -> str:
    """THE canonical heading input classification scores against — the exact
    string heading signals run over. It covers every structural heading input
    (full heading path + section title) and is the value the section
    signature commits to, using this same canonicalization."""
    return _fold(" / ".join(draft.heading_path) + " / " + draft.title)


def classify_section(
    draft: SectionDraft,
    module: DomainModule,
    *,
    anchor_id: str,
) -> SectionClassification:
    """Classify one section deterministically. Pure: same draft + same module
    + same anchor identity => the same result and the same signature. The
    signature covers the exact canonical heading input used for scoring, so
    two sections that differ only in heading input can never share one."""
    compiled = _compile_module(module)
    heading_text = classification_heading_input(draft)
    body_text = _fold(draft.text)

    weights = module.weights
    thresholds = module.thresholds

    matched_rules: List[str] = []

    # -- category (single best above threshold; fallback = explicit unknown) -- #
    best_category: Optional[str] = None
    best_score = 0.0
    best_rule: Optional[str] = None
    for rule in compiled.categories:
        excluded = [rid for rid, pattern in rule.exclusions if pattern.search(body_text) or pattern.search(heading_text)]
        if excluded:
            matched_rules.extend(excluded)
            continue  # suppressed: the exclusion phrase negates this rule for this section
        heading_hits = _count_hits(rule.heading_signals, heading_text)
        body_hits = _count_hits(rule.signals, body_text)
        phrase_hits = _count_hits(rule.phrases, body_text)
        score = (
            weights["headingSignal"] * len(heading_hits)
            + weights["bodySignal"] * len(body_hits)
            + weights["phrase"] * len(phrase_hits)
        )
        if score < thresholds["categoryMinScore"]:
            continue
        # Stable tie-breaking: higher score wins; equal scores resolve to the
        # lexicographically smallest category id (data-independent, stable).
        if score > best_score or (score == best_score and (best_category is None or rule.category < best_category)):
            best_category, best_score, best_rule = rule.category, score, rule.rule_id

    category = best_category if best_category is not None else module.fallback_category
    if best_rule is not None:
        matched_rules.append(best_rule)

    # -- topics --------------------------------------------------------------- #
    topics: List[str] = []
    for rule_id, label, signals, phrases in compiled.topics:
        phrase_hits = _count_hits(phrases, body_text)
        signal_hits = _count_hits(signals, body_text)
        if phrase_hits or len(signal_hits) >= int(thresholds["topicMinSignals"]):
            topics.append(label)
            matched_rules.append(rule_id)

    # -- market flags ---------------------------------------------------------- #
    market_flags: List[str] = []
    for rule_id, market, signals, phrases in compiled.markets:
        phrase_hits = _count_hits(phrases, body_text)
        signal_hits = _count_hits(signals, body_text)
        if phrase_hits or len(signal_hits) >= int(thresholds["marketMinSignals"]):
            market_flags.append(market)
            matched_rules.append(rule_id)

    # -- persona affinity ------------------------------------------------------ #
    persona_affinity: Dict[str, float] = {}
    for persona_id, needles in compiled.personas:
        hits = _count_hits(needles, body_text)
        if hits:
            persona_affinity[persona_id] = round(len(hits) / len(needles), 4)

    # -- keywords (display/search only) ----------------------------------------- #
    counts: Dict[str, int] = {}
    for token in _TOKEN_RE.findall(body_text):
        if token in _KEYWORD_STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    keywords = [t for t, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_MAX_KEYWORDS]]

    # -- injection flags --------------------------------------------------------- #
    injection_flags: List[str] = []
    for flag, pattern in _INJECTION_PATTERNS:
        if pattern.search(body_text):
            injection_flags.append(flag)
            matched_rules.append(f"classifier.injection.{flag}")

    matched_rules = sorted(set(matched_rules))

    signature = section_signature(
        anchor_id=anchor_id,
        text_sha256=draft.text_sha256,
        heading_input=heading_text,
        module=module,
        category=category,
        topics=topics,
        market_flags=market_flags,
        persona_affinity=persona_affinity,
        keywords=keywords,
        injection_flags=injection_flags,
        matched_rules=matched_rules,
    )

    return SectionClassification(
        category=category,
        topics=topics,
        market_flags=market_flags,
        persona_affinity=persona_affinity,
        keywords=keywords,
        injection_flags=injection_flags,
        matched_rules=matched_rules,
        signature=signature,
    )


def section_signature(
    *,
    anchor_id: str,
    text_sha256: str,
    heading_input: str,
    module: DomainModule,
    category: str,
    topics: Sequence[str],
    market_flags: Sequence[str],
    persona_affinity: Dict[str, float],
    keywords: Sequence[str],
    injection_flags: Sequence[str],
    matched_rules: Sequence[str],
) -> str:
    """The per-section deterministic classification signature: canonical JSON
    over the classification inputs/outputs and every load-bearing version —
    no timestamps, no DB row ids, no transient execution metadata.
    ``heading_input`` is the exact canonical heading string classification
    scored against (`classification_heading_input`), so two different heading
    inputs can never share a signature even when their outputs coincide."""
    payload = {
        "v": SECTION_SIGNATURE_VERSION,
        "anchorId": anchor_id,
        "textSha256": text_sha256,
        "headingInput": heading_input,
        "classifierVersion": CLASSIFIER_VERSION,
        "module": {"id": module.module_id, "version": module.version, "digest": module.digest},
        "thresholds": dict(module.thresholds),
        "weights": dict(module.weights),
        "category": category,
        "topics": list(topics),
        "marketFlags": list(market_flags),
        "personaAffinity": persona_affinity,
        "keywords": list(keywords),
        "injectionFlags": list(injection_flags),
        "matchedRules": list(matched_rules),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def version_signature(section_signatures: Sequence[str], module: DomainModule) -> str:
    """Version-level classification signature over the ordered per-section
    signatures + engine/module identity."""
    payload = {
        "v": 1,
        "classifierVersion": CLASSIFIER_VERSION,
        "module": {"id": module.module_id, "version": module.version, "digest": module.digest},
        "sections": list(section_signatures),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
