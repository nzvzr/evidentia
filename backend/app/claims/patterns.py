"""Strict loader for the non-executable claim-patterns-v1 JSON format."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from app.contracts import CLAIM_FAMILIES, ClaimSpec
from app.modules.loader import ACTIVE_MODULE_ID, ACTIVE_MODULE_VERSION, canonical_json

PATTERN_SCHEMA_VERSION = "claim-patterns-v1"
PATTERN_ENGINE_VERSION = "claim-pattern-engine-v1"
MAX_MATCHER_DEPTH = 12
MAX_MATCHER_NODES = 128
MAX_EVIDENCE_COUNT_NESTING = 1
MAX_TERM_LENGTH = 160
MAX_TERMS = 64

ACTIVE_CLAIM_PACK_ID = "compliance.claim-patterns"
ACTIVE_CLAIM_PACK_VERSION = "1.0.0"

_MODULE_ROOT = Path(__file__).resolve().parents[1] / "modules"
_SEMVER = re.compile(r"\A(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z", re.ASCII)
_ID = re.compile(r"\A[a-z0-9]+(?:[._-][a-z0-9]+)+\Z", re.ASCII)


class PatternValidationError(ValueError):
    """Pattern data is malformed. Loading fails as one atomic release."""


@dataclass(frozen=True)
class GatePolicy:
    policy_id: str
    version: str
    accept_threshold: Decimal
    reject_below: Decimal
    weights: Mapping[str, Decimal]


@dataclass(frozen=True)
class ClaimPatternRelease:
    schema_version: str
    claim_pack_id: str
    release_version: str
    module_id: str
    module_version: str
    release_digest: str
    specs: tuple[ClaimSpec, ...]
    policies: Mapping[str, GatePolicy]
    raw: Mapping[str, Any]


def _fail(message: str) -> None:
    raise PatternValidationError(message)


def _strict_object(value: Any, where: str, allowed: set[str], required: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{where} must be an object")
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        _fail(f"{where} has unknown fields: {', '.join(unknown)}")
    if missing:
        _fail(f"{where} is missing fields: {', '.join(missing)}")
    return value


def _string(value: Any, where: str, *, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _fail(f"{where} must be a non-empty string of at most {limit} characters")
    out = value.strip()
    folded = out.casefold()
    if "://" in folded or folded.startswith(("file:", "../", "..\\", "./", ".\\")):
        _fail(f"{where} may not reference external files or networks")
    if any(marker in folded for marker in ("__import__", "eval(", "exec(", "lambda ", "{%", "{{")):
        _fail(f"{where} contains executable/template content")
    return out


def _decimal(value: Any, where: str, *, minimum: float = 0.0, maximum: float = 1.0) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{where} must be a number")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        _fail(f"{where} must be a finite decimal number")
    if not result.is_finite() or result < Decimal(str(minimum)) or result > Decimal(str(maximum)):
        _fail(f"{where} must be between {minimum} and {maximum}")
    return result


def _number(value: Any, where: str, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return float(_decimal(value, where, minimum=minimum, maximum=maximum))


def _relative_path(value: Any, where: str) -> str:
    out = _string(value, where, limit=160)
    candidate = Path(out)
    if candidate.is_absolute() or candidate.drive or any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{where} must be a safe release-relative path")
    if out.startswith(("/", "\\")) or re.match(r"\A[a-zA-Z]:", out):
        _fail(f"{where} must be a safe release-relative path")
    return out


def _terms(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > MAX_TERMS:
        _fail(f"{where} must contain 1..{MAX_TERMS} strings")
    terms = tuple(_string(item, f"{where}[]", limit=MAX_TERM_LENGTH) for item in value)
    if len(set(terms)) != len(terms):
        _fail(f"{where} contains duplicate terms")
    return terms


_PRIMITIVE_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    "token_any": ({"primitive", "terms"}, {"terms"}),
    "token_all": ({"primitive", "terms"}, {"terms"}),
    "exact_phrase": ({"primitive", "phrases"}, {"phrases"}),
    "proximity": ({"primitive", "left", "right", "maxTokens"}, {"left", "right", "maxTokens"}),
    "heading_match": ({"primitive", "terms", "mode"}, {"terms"}),
    "classification_match": ({"primitive", "categories", "topics", "match"}, set()),
    "obligation_term": ({"primitive", "terms"}, {"terms"}),
    "prohibition_term": ({"primitive", "terms"}, {"terms"}),
    "negation": ({"primitive", "terms", "windowTokens"}, {"terms"}),
    "numeric_value": ({"primitive", "min", "max", "units"}, set()),
    "duration_deadline": ({"primitive", "minHours", "maxHours", "terms"}, set()),
    "evidence_count": ({"primitive", "matcher", "min", "max"}, {"matcher", "min"}),
    "all_of": ({"primitive", "children"}, {"children"}),
    "any_of": ({"primitive", "children"}, {"children"}),
    "not": ({"primitive", "child"}, {"child"}),
    "minimum_should_match": ({"primitive", "children", "minimum"}, {"children", "minimum"}),
}


def validate_matcher(
    value: Any,
    where: str = "matcher",
    *,
    depth: int = 0,
    counter: list[int] | None = None,
    evidence_count_nesting: int = 0,
) -> dict[str, Any]:
    if depth > MAX_MATCHER_DEPTH:
        _fail(f"{where} exceeds maximum depth {MAX_MATCHER_DEPTH}")
    counter = counter if counter is not None else [0]
    counter[0] += 1
    if counter[0] > MAX_MATCHER_NODES:
        _fail(f"{where} exceeds maximum node count {MAX_MATCHER_NODES}")
    if not isinstance(value, dict):
        _fail(f"{where} must be an object")
    primitive = value.get("primitive")
    if primitive not in _PRIMITIVE_FIELDS:
        _fail(f"{where} uses unknown primitive {primitive!r}")
    allowed, required = _PRIMITIVE_FIELDS[primitive]
    node = _strict_object(value, where, allowed, {"primitive", *required})

    if "terms" in node:
        _terms(node["terms"], f"{where}.terms")
    if "phrases" in node:
        _terms(node["phrases"], f"{where}.phrases")
    if primitive == "proximity":
        _terms(node["left"], f"{where}.left")
        _terms(node["right"], f"{where}.right")
        if not isinstance(node["maxTokens"], int) or not 1 <= node["maxTokens"] <= 100:
            _fail(f"{where}.maxTokens must be an integer between 1 and 100")
    if primitive == "heading_match" and node.get("mode", "any") not in {"any", "all", "phrase"}:
        _fail(f"{where}.mode is invalid")
    if primitive == "classification_match":
        if not node.get("categories") and not node.get("topics"):
            _fail(f"{where} requires categories or topics")
        for key in ("categories", "topics"):
            if key in node:
                _terms(node[key], f"{where}.{key}")
        if node.get("match", "any") not in {"any", "all"}:
            _fail(f"{where}.match is invalid")
    if primitive == "negation" and (not isinstance(node.get("windowTokens", 8), int) or not 1 <= node.get("windowTokens", 8) <= 40):
        _fail(f"{where}.windowTokens must be between 1 and 40")
    if primitive == "numeric_value":
        for key in ("min", "max"):
            if key in node:
                _number(node[key], f"{where}.{key}", minimum=-1_000_000_000, maximum=1_000_000_000)
        if "units" in node:
            _terms(node["units"], f"{where}.units")
        if "min" in node and "max" in node and float(node["min"]) > float(node["max"]):
            _fail(f"{where}.min exceeds max")
    if primitive == "duration_deadline":
        for key in ("minHours", "maxHours"):
            if key in node:
                _number(node[key], f"{where}.{key}", minimum=0, maximum=876_000)
        if "minHours" in node and "maxHours" in node and float(node["minHours"]) > float(node["maxHours"]):
            _fail(f"{where}.minHours exceeds maxHours")
    if primitive in {"all_of", "any_of", "minimum_should_match"}:
        children = node["children"]
        if not isinstance(children, list) or not children or len(children) > 32:
            _fail(f"{where}.children must contain 1..32 matchers")
        for index, child in enumerate(children):
            validate_matcher(
                child,
                f"{where}.children[{index}]",
                depth=depth + 1,
                counter=counter,
                evidence_count_nesting=evidence_count_nesting,
            )
        if primitive == "minimum_should_match" and (
            not isinstance(node["minimum"], int) or not 1 <= node["minimum"] <= len(children)
        ):
            _fail(f"{where}.minimum is invalid")
    if primitive == "not":
        validate_matcher(
            node["child"],
            f"{where}.child",
            depth=depth + 1,
            counter=counter,
            evidence_count_nesting=evidence_count_nesting,
        )
    if primitive == "evidence_count":
        if evidence_count_nesting >= MAX_EVIDENCE_COUNT_NESTING:
            _fail(f"{where} exceeds maximum evidence_count nesting {MAX_EVIDENCE_COUNT_NESTING}")
        validate_matcher(
            node["matcher"],
            f"{where}.matcher",
            depth=depth + 1,
            counter=counter,
            evidence_count_nesting=evidence_count_nesting + 1,
        )
        if not isinstance(node["min"], int) or not 0 <= node["min"] <= 1000:
            _fail(f"{where}.min is invalid")
        if "max" in node and (not isinstance(node["max"], int) or node["max"] < node["min"] or node["max"] > 1000):
            _fail(f"{where}.max is invalid")
    return node


def _load_release(
    module_id: str,
    claim_pack_version: str,
    *,
    module_version: str = ACTIVE_MODULE_VERSION,
) -> ClaimPatternRelease:
    if not _SEMVER.fullmatch(claim_pack_version):
        _fail("claim pack version must be canonical semver")
    path = _MODULE_ROOT / module_id / "claim-patterns" / claim_pack_version / "claim-patterns.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PatternValidationError(f"claim pattern release unreadable: {exc}") from exc
    root = _strict_object(
        raw,
        "release",
        {"schemaVersion", "claimPackId", "releaseVersion", "moduleId", "moduleVersion", "gatePolicies", "patterns", "provenance"},
        {"schemaVersion", "claimPackId", "releaseVersion", "moduleId", "moduleVersion", "gatePolicies", "patterns", "provenance"},
    )
    if root["schemaVersion"] != PATTERN_SCHEMA_VERSION:
        _fail("unsupported claim pattern schema version")
    release_version = _string(root["releaseVersion"], "release.releaseVersion", limit=40)
    claim_pack_id = _string(root["claimPackId"], "release.claimPackId", limit=160)
    if claim_pack_id != f"{module_id}.claim-patterns":
        _fail("claim release pack identity mismatch")
    if not _SEMVER.fullmatch(release_version) or release_version != claim_pack_version:
        _fail("release.releaseVersion must be canonical semver")
    if root["moduleId"] != module_id or root["moduleVersion"] != module_version:
        _fail("claim release module identity mismatch")
    _strict_object(root["provenance"], "release.provenance", {"releasedAt", "changelog", "fixturePack"}, {"releasedAt", "changelog", "fixturePack"})
    _string(root["provenance"]["releasedAt"], "release.provenance.releasedAt", limit=40)
    _string(root["provenance"]["changelog"], "release.provenance.changelog", limit=1000)
    _relative_path(root["provenance"]["fixturePack"], "release.provenance.fixturePack")

    if not isinstance(root["gatePolicies"], list) or not root["gatePolicies"]:
        _fail("release.gatePolicies must be a non-empty list")
    policies: dict[str, GatePolicy] = {}
    for index, item in enumerate(root["gatePolicies"]):
        where = f"release.gatePolicies[{index}]"
        obj = _strict_object(item, where, {"id", "version", "acceptThreshold", "rejectBelow", "weights"}, {"id", "version", "acceptThreshold", "rejectBelow", "weights"})
        policy_id = _string(obj["id"], f"{where}.id", limit=100)
        version = _string(obj["version"], f"{where}.version", limit=40)
        if policy_id in policies or not _SEMVER.fullmatch(version):
            _fail(f"{where} has duplicate id or invalid version")
        weights_obj = _strict_object(
            obj["weights"], f"{where}.weights",
            {"requirementCoverage", "matcherSupport", "bindingCount", "sourceDiversity", "obligation", "contradictionPenalty"},
            {"requirementCoverage", "matcherSupport", "bindingCount", "sourceDiversity", "obligation", "contradictionPenalty"},
        )
        weights = {key: _decimal(value, f"{where}.weights.{key}", minimum=0, maximum=2) for key, value in weights_obj.items()}
        accept = _decimal(obj["acceptThreshold"], f"{where}.acceptThreshold")
        reject = _decimal(obj["rejectBelow"], f"{where}.rejectBelow")
        if reject >= accept:
            _fail(f"{where}.rejectBelow must be lower than acceptThreshold")
        policies[policy_id] = GatePolicy(policy_id, version, accept, reject, weights)

    patterns = root["patterns"]
    if not isinstance(patterns, list) or not 1 <= len(patterns) <= 100:
        _fail("release.patterns must contain 1..100 patterns")
    ids: set[str] = set()
    specs: list[ClaimSpec] = []
    for index, item in enumerate(patterns):
        where = f"release.patterns[{index}]"
        obj = _strict_object(
            item, where,
            {"id", "version", "title", "family", "claimType", "priorityHint", "enabled", "evidenceNeeds", "matcher", "gatePolicy", "output", "provenance"},
            {"id", "version", "title", "family", "claimType", "enabled", "evidenceNeeds", "matcher", "gatePolicy", "output", "provenance"},
        )
        pattern_id = _string(obj["id"], f"{where}.id", limit=160)
        if pattern_id in ids or not _ID.fullmatch(pattern_id) or not pattern_id.startswith(f"{module_id}."):
            _fail(f"{where}.id is duplicate or not a namespaced canonical id")
        ids.add(pattern_id)
        version = _string(obj["version"], f"{where}.version", limit=40)
        if not _SEMVER.fullmatch(version):
            _fail(f"{where}.version must be canonical semver")
        if obj["family"] not in CLAIM_FAMILIES:
            _fail(f"{where}.family is invalid")
        if not isinstance(obj["enabled"], bool):
            _fail(f"{where}.enabled must be boolean")
        matcher = validate_matcher(obj["matcher"], f"{where}.matcher")
        needs_raw = obj["evidenceNeeds"]
        if not isinstance(needs_raw, list) or not 1 <= len(needs_raw) <= 16:
            _fail(f"{where}.evidenceNeeds must contain 1..16 entries")
        needs: list[dict[str, Any]] = []
        need_ids: set[str] = set()
        for nindex, need in enumerate(needs_raw):
            nwhere = f"{where}.evidenceNeeds[{nindex}]"
            nobj = _strict_object(need, nwhere, {"id", "required", "weight", "purpose", "matcher"}, {"id", "required", "weight", "matcher"})
            need_id = _string(nobj["id"], f"{nwhere}.id", limit=100)
            if need_id in need_ids or not _ID.fullmatch(f"x.{need_id}"):
                _fail(f"{nwhere}.id is invalid or duplicate")
            need_ids.add(need_id)
            if not isinstance(nobj["required"], bool):
                _fail(f"{nwhere}.required must be boolean")
            purpose = nobj.get("purpose", "support")
            if purpose not in {"support", "conflict"}:
                _fail(f"{nwhere}.purpose is invalid")
            needs.append({
                "id": need_id,
                "required": nobj["required"],
                "weight": _number(nobj["weight"], f"{nwhere}.weight", minimum=0.01, maximum=10),
                "purpose": purpose,
                "matcher": validate_matcher(nobj["matcher"], f"{nwhere}.matcher"),
            })
        gate_ref = _strict_object(obj["gatePolicy"], f"{where}.gatePolicy", {"id", "version"}, {"id", "version"})
        policy_id = _string(gate_ref["id"], f"{where}.gatePolicy.id", limit=100)
        if policy_id not in policies or gate_ref["version"] != policies[policy_id].version:
            _fail(f"{where}.gatePolicy references an unknown policy version")
        output = _strict_object(
            obj["output"], f"{where}.output",
            {"kind", "statement", "severity", "title", "description", "businessImpact", "recommendedFix", "owner"},
            {"kind", "statement"},
        )
        if output["kind"] not in {"risk", "finding", "workflow", "recommendation"}:
            _fail(f"{where}.output.kind is invalid")
        output_clean = {key: _string(value, f"{where}.output.{key}", limit=1000) for key, value in output.items()}
        provenance = _strict_object(obj["provenance"], f"{where}.provenance", {"changelog", "fixtures"}, {"changelog", "fixtures"})
        _string(provenance["changelog"], f"{where}.provenance.changelog", limit=1000)
        if not isinstance(provenance["fixtures"], list) or not provenance["fixtures"]:
            _fail(f"{where}.provenance.fixtures must be a non-empty list")
        tuple(_string(value, f"{where}.provenance.fixtures[]", limit=160) for value in provenance["fixtures"])
        digest = hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
        specs.append(ClaimSpec(
            id=pattern_id,
            module=module_id,
            version=version,
            family=obj["family"],
            title=_string(obj["title"], f"{where}.title", limit=300),
            claim_type=_string(obj["claimType"], f"{where}.claimType", limit=100),
            priority_hint=_string(obj["priorityHint"], f"{where}.priorityHint", limit=40) if obj.get("priorityHint") else None,
            evidence_needs=tuple(needs),
            matcher=matcher,
            gate_policy_id=policy_id,
            gate_policy_version=policies[policy_id].version,
            output_metadata=output_clean,
            enabled=obj["enabled"],
            provenance=dict(provenance),
            pattern_digest=digest,
            templates={"statement": output_clean["statement"]},
            severity_policy={"priorityHint": obj.get("priorityHint")},
        ))

    digest = hashlib.sha256(canonical_json(root).encode("utf-8")).hexdigest()
    return ClaimPatternRelease(
        PATTERN_SCHEMA_VERSION,
        claim_pack_id,
        release_version,
        module_id,
        module_version,
        digest,
        tuple(specs),
        policies,
        root,
    )


@lru_cache(maxsize=8)
def load_claim_patterns(
    module_id: str,
    claim_pack_version: str,
    *,
    module_version: str = ACTIVE_MODULE_VERSION,
) -> ClaimPatternRelease:
    return _load_release(module_id, claim_pack_version, module_version=module_version)


def load_active_claim_patterns() -> ClaimPatternRelease:
    return load_claim_patterns(
        ACTIVE_MODULE_ID,
        ACTIVE_CLAIM_PACK_VERSION,
        module_version=ACTIVE_MODULE_VERSION,
    )
