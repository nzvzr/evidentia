"""Closed, typed, deterministic matcher primitive registry (M5a)."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

MATCHER_ENGINE_VERSION = "typed-matchers-v1"
MAX_EVIDENCE_ITEMS = 500
MAX_TEXT_CHARS = 80_000
MAX_TOTAL_PRIMITIVE_EVALUATIONS = 4_096

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_NUMBER_RE = re.compile(r"(?<![\w.])([0-9]+(?:\.[0-9]+)?)(?![\w.])", re.ASCII)
_DURATION_RE = re.compile(
    r"(?<![\w.])([0-9]+(?:\.[0-9]+)?)\s*(minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?)(?!\w)",
    re.IGNORECASE | re.ASCII,
)


def normalize_text(value: str) -> str:
    """Explicit matcher normalization: NFKC, casefold, canonical whitespace."""
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


@dataclass(frozen=True)
class EvidenceContext:
    binding_id: str
    citation_id: str
    document_id: str
    version_id: str
    anchor_id: str
    text: str
    heading: str
    category: str | None = None
    topics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.binding_id or not self.citation_id or not self.document_id:
            raise ValueError("evidence context identity is incomplete")
        if not isinstance(self.text, str) or len(self.text) > MAX_TEXT_CHARS:
            raise ValueError("evidence text is malformed or exceeds the matcher bound")


@dataclass(frozen=True)
class MatcherObservation:
    primitive: str
    matched: bool
    binding_ids: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = ()
    spans: tuple[tuple[int, int], ...] = ()
    values: tuple[float, ...] = ()
    children: tuple["MatcherObservation", ...] = ()

    def audit_dict(self) -> dict[str, Any]:
        return {
            "primitive": self.primitive,
            "matched": self.matched,
            "bindingIds": list(self.binding_ids),
            "matchedTerms": list(self.matched_terms),
            "spans": [list(span) for span in self.spans],
            "values": list(self.values),
            "children": [child.audit_dict() for child in self.children],
        }


@dataclass
class MatcherEvaluationBudget:
    """One deterministic work budget shared by every matcher for a candidate."""

    remaining_primitive_evaluations: int = MAX_TOTAL_PRIMITIVE_EVALUATIONS

    def consume(self) -> None:
        self.remaining_primitive_evaluations -= 1
        if self.remaining_primitive_evaluations < 0:
            raise ValueError("matcher primitive evaluation budget exceeded")


def _token_positions(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    tokens: list[str] = []
    spans: list[tuple[int, int]] = []
    for match in _TOKEN_RE.finditer(text):
        tokens.append(match.group(0))
        spans.append((match.start(), match.end()))
    return tokens, spans


def _term_hits(text: str, terms: Sequence[str]) -> tuple[tuple[str, ...], tuple[tuple[int, int], ...]]:
    hits: list[tuple[str, int, int]] = []
    for term in terms:
        normalized = normalize_text(term)
        if not normalized:
            continue
        if " " in normalized:
            start = text.find(normalized)
            while start >= 0:
                hits.append((normalized, start, start + len(normalized)))
                start = text.find(normalized, start + max(1, len(normalized)))
        else:
            for match in _TOKEN_RE.finditer(text):
                if match.group(0) == normalized:
                    hits.append((normalized, match.start(), match.end()))
    hits.sort(key=lambda item: (item[1], item[2], item[0]))
    return tuple(sorted({item[0] for item in hits})), tuple((item[1], item[2]) for item in hits)


def _leaf_across_evidence(
    primitive: str,
    evidence: Sequence[EvidenceContext],
    evaluator: Any,
) -> MatcherObservation:
    binding_ids: list[str] = []
    terms: set[str] = set()
    spans: list[tuple[int, int]] = []
    values: list[float] = []
    for item in evidence:
        matched, item_terms, item_spans, item_values = evaluator(item)
        if matched:
            binding_ids.append(item.binding_id)
            terms.update(item_terms)
            spans.extend(item_spans)
            values.extend(item_values)
    return MatcherObservation(
        primitive=primitive,
        matched=bool(binding_ids),
        binding_ids=tuple(sorted(set(binding_ids))),
        matched_terms=tuple(sorted(terms)),
        spans=tuple(sorted(set(spans))),
        values=tuple(sorted(values)),
    )


def _duration_hours(value: float, unit: str) -> float:
    unit = unit.casefold()
    if unit.startswith(("minute", "min")):
        return value / 60.0
    if unit.startswith(("hour", "hr")):
        return value
    if unit.startswith("day"):
        return value * 24.0
    if unit.startswith("week"):
        return value * 168.0
    if unit.startswith("month"):
        return value * 730.0
    return value * 8760.0


def evaluate_matcher(
    node: Mapping[str, Any],
    evidence: Sequence[EvidenceContext],
    features: Mapping[str, float] | None = None,
    *,
    budget: MatcherEvaluationBudget | None = None,
) -> MatcherObservation:
    """Evaluate one validated matcher tree with stable ordering and bounded work."""
    if len(evidence) > MAX_EVIDENCE_ITEMS:
        raise ValueError("evidence count exceeds matcher bound")
    budget = budget or MatcherEvaluationBudget()
    budget.consume()
    evidence = tuple(sorted(evidence, key=lambda item: (item.document_id, item.version_id, item.anchor_id, item.binding_id)))
    primitive = str(node["primitive"])
    features = features or {}

    if primitive in {"token_any", "token_all", "exact_phrase", "obligation_term", "prohibition_term"}:
        key = "phrases" if primitive == "exact_phrase" else "terms"
        wanted = tuple(normalize_text(value) for value in node[key])

        def evaluator(item: EvidenceContext):
            matched_terms, spans = _term_hits(normalize_text(item.text), wanted)
            matched = len(matched_terms) == len(wanted) if primitive == "token_all" else bool(matched_terms)
            return matched, matched_terms, spans, ()

        return _leaf_across_evidence(primitive, evidence, evaluator)

    if primitive == "heading_match":
        wanted = tuple(normalize_text(value) for value in node["terms"])
        mode = node.get("mode", "any")

        def evaluator(item: EvidenceContext):
            text = normalize_text(item.heading)
            matched_terms, spans = _term_hits(text, wanted)
            matched = (
                len(matched_terms) == len(wanted)
                if mode == "all"
                else any(normalize_text(value) in text for value in wanted)
                if mode == "phrase"
                else bool(matched_terms)
            )
            return matched, matched_terms, spans, ()

        return _leaf_across_evidence(primitive, evidence, evaluator)

    if primitive == "classification_match":
        categories = {normalize_text(value) for value in node.get("categories", [])}
        topics = {normalize_text(value) for value in node.get("topics", [])}
        mode = node.get("match", "any")

        def evaluator(item: EvidenceContext):
            actual = ({normalize_text(item.category or "")} if categories else set()) | {
                normalize_text(topic) for topic in item.topics
            }
            wanted = categories | topics
            matched_values = tuple(sorted(actual & wanted))
            matched = wanted <= actual if mode == "all" else bool(matched_values)
            return matched, matched_values, (), ()

        return _leaf_across_evidence(primitive, evidence, evaluator)

    if primitive == "proximity":
        left = {normalize_text(value) for value in node["left"]}
        right = {normalize_text(value) for value in node["right"]}
        distance = int(node["maxTokens"])

        def evaluator(item: EvidenceContext):
            text = normalize_text(item.text)
            tokens, token_spans = _token_positions(text)
            left_positions = [(i, token) for i, token in enumerate(tokens) if token in left]
            right_positions = [(i, token) for i, token in enumerate(tokens) if token in right]
            matches: list[tuple[int, int, str, str]] = []
            for li, lt in left_positions:
                for ri, rt in right_positions:
                    # ``left`` then ``right`` is intentional and audited. It
                    # lets patterns express bounded negation ("not ... MFA")
                    # without a later unrelated "not" reaching backwards.
                    if 0 <= ri - li <= distance:
                        start = min(token_spans[li][0], token_spans[ri][0])
                        end = max(token_spans[li][1], token_spans[ri][1])
                        matches.append((start, end, lt, rt))
            matches.sort()
            return bool(matches), tuple(sorted({v for m in matches for v in m[2:]})), tuple((m[0], m[1]) for m in matches), ()

        return _leaf_across_evidence(primitive, evidence, evaluator)

    if primitive == "negation":
        terms = {normalize_text(value) for value in node["terms"]}
        window = int(node.get("windowTokens", 8))

        def evaluator(item: EvidenceContext):
            text = normalize_text(item.text)
            tokens, token_spans = _token_positions(text)
            hits = [(i, token) for i, token in enumerate(tokens) if token in terms]
            spans = []
            for index, _token in hits:
                spans.append((token_spans[max(0, index - window)][0], token_spans[min(len(tokens) - 1, index + window)][1]))
            return bool(hits), tuple(sorted({item[1] for item in hits})), tuple(spans), ()

        return _leaf_across_evidence(primitive, evidence, evaluator)

    if primitive == "numeric_value":
        minimum = float(node.get("min", -math.inf))
        maximum = float(node.get("max", math.inf))
        units = tuple(normalize_text(value) for value in node.get("units", []))

        def evaluator(item: EvidenceContext):
            text = normalize_text(item.text)
            values: list[float] = []
            spans: list[tuple[int, int]] = []
            for match in _NUMBER_RE.finditer(text):
                suffix = text[match.end() : match.end() + 40].lstrip()
                if units and not any(suffix.startswith(unit) for unit in units):
                    continue
                value = float(match.group(1))
                if minimum <= value <= maximum:
                    values.append(value)
                    spans.append((match.start(), match.end()))
            return bool(values), (), tuple(spans), tuple(values)

        return _leaf_across_evidence(primitive, evidence, evaluator)

    if primitive == "duration_deadline":
        minimum = float(node.get("minHours", 0))
        maximum = float(node.get("maxHours", math.inf))
        terms = tuple(normalize_text(value) for value in node.get("terms", []))

        def evaluator(item: EvidenceContext):
            text = normalize_text(item.text)
            if terms and not any(term in text for term in terms):
                return False, (), (), ()
            values: list[float] = []
            spans: list[tuple[int, int]] = []
            for match in _DURATION_RE.finditer(text):
                hours = _duration_hours(float(match.group(1)), match.group(2))
                if minimum <= hours <= maximum:
                    values.append(hours)
                    spans.append((match.start(), match.end()))
            return bool(values), tuple(sorted(term for term in terms if term in text)), tuple(spans), tuple(values)

        return _leaf_across_evidence(primitive, evidence, evaluator)

    if primitive in {"all_of", "any_of", "minimum_should_match"}:
        children = tuple(
            evaluate_matcher(child, evidence, features, budget=budget)
            for child in node["children"]
        )
        count = sum(1 for child in children if child.matched)
        matched = count == len(children) if primitive == "all_of" else count >= (int(node["minimum"]) if primitive == "minimum_should_match" else 1)
        bindings = tuple(sorted({binding for child in children if child.matched for binding in child.binding_ids}))
        return MatcherObservation(primitive, matched, bindings, children=children)

    if primitive == "not":
        child = evaluate_matcher(node["child"], evidence, features, budget=budget)
        return MatcherObservation(primitive, not child.matched, children=(child,))

    if primitive == "evidence_count":
        child_node = node["matcher"]
        matching_bindings: list[str] = []
        children: list[MatcherObservation] = []
        for item in evidence:
            observation = evaluate_matcher(child_node, (item,), features, budget=budget)
            children.append(observation)
            if observation.matched:
                matching_bindings.append(item.binding_id)
        count = len(set(matching_bindings))
        matched = count >= int(node["min"]) and ("max" not in node or count <= int(node["max"]))
        return MatcherObservation(primitive, matched, tuple(sorted(set(matching_bindings))), values=(float(count),), children=tuple(children))

    raise ValueError(f"unsupported validated primitive {primitive!r}")


def flatten_observations(observation: MatcherObservation) -> tuple[MatcherObservation, ...]:
    values = [observation]
    for child in observation.children:
        values.extend(flatten_observations(child))
    return tuple(values)
