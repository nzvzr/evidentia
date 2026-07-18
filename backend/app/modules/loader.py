"""Domain-module loader: deterministic, schema-validated, fail-closed (M3).

A domain module is a **versioned data pack** (PLATFORM_ARCHITECTURE.md §3):
typed declarative data the classification engine executes, never code. This
loader:

* reads the module's JSON files from ``app/modules/<id>/<version>/`` —
  local files only, no remote loading, no dynamic code execution, and no
  tenant-provided content ever reaches this path;
* validates every field against the typed schema below — an invalid module
  **fails closed** (`ModuleValidationError`), it is never partially applied;
* computes a **stable module digest** (sha256 over the canonical JSON of the
  whole pack) that participates in classification signatures and manifests,
  so any data change is provable downstream.

Adding a future module is adding a directory — the engine code does not
change (`get_active_module` grows a registry entry; the classifier stays
generic).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

_MODULES_ROOT = Path(__file__).resolve().parent

# The single module shipped in M3. Tenant-level module registries arrive with
# a later milestone; until then the platform runs exactly this pack.
ACTIVE_MODULE_ID = "compliance"
ACTIVE_MODULE_VERSION = "1.0.0"

_REQUIRED_FILES = ("module.json", "taxonomy.json", "signatures.json")


class ModuleValidationError(Exception):
    """The module data pack is malformed. Classification must fail closed —
    never classify with a partially valid module."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModuleValidationError(message)


def _str_list(value: Any, where: str) -> Tuple[str, ...]:
    _require(isinstance(value, list), f"{where} must be a list")
    out: List[str] = []
    for item in value:
        _require(isinstance(item, str) and item.strip(), f"{where} entries must be non-empty strings")
        out.append(item)
    return tuple(out)


@dataclass(frozen=True)
class ExclusionRule:
    rule_id: str
    phrase: str


@dataclass(frozen=True)
class CategoryRule:
    rule_id: str
    category: str
    heading_signals: Tuple[str, ...]
    signals: Tuple[str, ...]
    phrases: Tuple[str, ...]
    exclusions: Tuple[ExclusionRule, ...] = ()


@dataclass(frozen=True)
class TopicRule:
    rule_id: str
    topic_id: str
    label: str
    signals: Tuple[str, ...]
    phrases: Tuple[str, ...]


@dataclass(frozen=True)
class MarketRule:
    rule_id: str
    market: str
    signals: Tuple[str, ...]
    phrases: Tuple[str, ...]


@dataclass(frozen=True)
class PersonaNeedles:
    persona_id: str
    needles: Tuple[str, ...]


@dataclass(frozen=True)
class DomainModule:
    """A fully validated, digested module pack."""

    module_id: str
    version: str
    digest: str  # sha256 hex over the canonical JSON of the whole pack
    description: str
    # module.json engineCompatibility: engine name -> versions this pack
    # supports (empty mapping = no declaration). ENFORCED by the classifier
    # (`ensure_module_compatible`) and by the complete finalization target.
    engine_compatibility: Mapping[str, Tuple[str, ...]]
    # signatures.json signatureVersion: the pack data format. Enforced against
    # the engine's supported set; participates in target support/eligibility.
    signature_version: str
    categories: Tuple[str, ...]           # includes the fallback
    fallback_category: str
    category_descriptions: Mapping[str, str]
    category_rules: Tuple[CategoryRule, ...]
    topic_rules: Tuple[TopicRule, ...]
    market_rules: Tuple[MarketRule, ...]
    personas: Tuple[PersonaNeedles, ...]
    thresholds: Mapping[str, float]
    weights: Mapping[str, float]
    fixture_names: Tuple[str, ...] = ()

    @property
    def signature_pack_version(self) -> str:
        """The provenance string persisted on classified sections."""
        return f"{self.module_id}@{self.version}"


def canonical_json(data: Any) -> str:
    """The one canonical serialization used for module digests, classification
    signatures and manifests: sorted keys, no whitespace, ASCII-escaped."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _read_json(directory: Path, name: str) -> Any:
    path = directory / name
    _require(path.is_file(), f"module file missing: {name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModuleValidationError(f"module file unreadable: {name}: {exc}") from exc


def _validate_thresholds(raw: Any) -> Dict[str, float]:
    _require(isinstance(raw, dict), "signatures.thresholds must be an object")
    out: Dict[str, float] = {}
    for key in ("categoryMinScore", "topicMinSignals", "marketMinSignals"):
        value = raw.get(key)
        _require(isinstance(value, (int, float)) and value > 0, f"threshold {key} must be > 0")
        out[key] = float(value)
    return out


def _validate_weights(raw: Any) -> Dict[str, float]:
    _require(isinstance(raw, dict), "signatures.weights must be an object")
    out: Dict[str, float] = {}
    for key in ("headingSignal", "bodySignal", "phrase"):
        value = raw.get(key)
        _require(isinstance(value, (int, float)) and value > 0, f"weight {key} must be > 0")
        out[key] = float(value)
    return out


def _load_and_validate(module_id: str, version: str) -> DomainModule:
    directory = _MODULES_ROOT / module_id / version
    _require(directory.is_dir(), f"module not found: {module_id}@{version}")

    raw: Dict[str, Any] = {name: _read_json(directory, name) for name in _REQUIRED_FILES}

    meta = raw["module.json"]
    _require(meta.get("id") == module_id, "module.json id mismatch")
    _require(meta.get("version") == version, "module.json version mismatch")
    description = str(meta.get("description", ""))
    fixture_names = _str_list(meta.get("fixtures", []), "module.json fixtures")

    raw_compat = meta.get("engineCompatibility", {})
    _require(isinstance(raw_compat, dict), "module.json engineCompatibility must be an object")
    engine_compatibility: Dict[str, Tuple[str, ...]] = {}
    for engine_name, versions in raw_compat.items():
        _require(
            isinstance(engine_name, str) and engine_name.strip(),
            "engineCompatibility keys must be engine names",
        )
        supported = _str_list(versions, f"engineCompatibility {engine_name}")
        _require(len(supported) > 0, f"engineCompatibility {engine_name} must list at least one version")
        engine_compatibility[engine_name] = supported

    taxonomy = raw["taxonomy.json"]
    _require(isinstance(taxonomy.get("categories"), list), "taxonomy.categories must be a list")
    categories: List[str] = []
    descriptions: Dict[str, str] = {}
    fallback: Optional[str] = None
    for entry in taxonomy["categories"]:
        _require(isinstance(entry, dict), "taxonomy category entries must be objects")
        cat = entry.get("id")
        _require(isinstance(cat, str) and cat.strip(), "taxonomy category id required")
        _require(cat not in categories, f"duplicate taxonomy category {cat!r}")
        categories.append(cat)
        descriptions[cat] = str(entry.get("description", ""))
        if entry.get("fallback"):
            _require(fallback is None, "taxonomy declares more than one fallback category")
            fallback = cat
    _require(fallback is not None, "taxonomy must declare exactly one fallback category")

    topic_rules: List[TopicRule] = []
    for entry in taxonomy.get("topics", []):
        _require(isinstance(entry, dict), "taxonomy topic entries must be objects")
        topic_id = entry.get("id")
        _require(isinstance(topic_id, str) and topic_id.strip(), "topic id required")
        topic_rules.append(
            TopicRule(
                rule_id=f"{module_id}.topic.{topic_id}",
                topic_id=topic_id,
                label=str(entry.get("label", topic_id)),
                signals=_str_list(entry.get("signals", []), f"topic {topic_id} signals"),
                phrases=_str_list(entry.get("phrases", []), f"topic {topic_id} phrases"),
            )
        )
    _require(
        len({t.topic_id for t in topic_rules}) == len(topic_rules), "duplicate topic ids"
    )

    market_rules: List[MarketRule] = []
    for entry in taxonomy.get("markets", []):
        _require(isinstance(entry, dict), "taxonomy market entries must be objects")
        market = entry.get("id")
        _require(isinstance(market, str) and market.strip(), "market id required")
        slug = "".join(ch for ch in market.lower() if ch.isalnum())
        market_rules.append(
            MarketRule(
                rule_id=f"{module_id}.market.{slug}",
                market=market,
                signals=_str_list(entry.get("signals", []), f"market {market} signals"),
                phrases=_str_list(entry.get("phrases", []), f"market {market} phrases"),
            )
        )
    _require(
        len({m.market for m in market_rules}) == len(market_rules), "duplicate market ids"
    )

    personas: List[PersonaNeedles] = []
    for entry in taxonomy.get("personas", []):
        _require(isinstance(entry, dict), "taxonomy persona entries must be objects")
        persona_id = entry.get("id")
        _require(isinstance(persona_id, str) and persona_id.strip(), "persona id required")
        needles = _str_list(entry.get("needles", []), f"persona {persona_id} needles")
        _require(len(needles) > 0, f"persona {persona_id} needs at least one needle")
        personas.append(PersonaNeedles(persona_id=persona_id, needles=needles))
    _require(
        len({p.persona_id for p in personas}) == len(personas), "duplicate persona ids"
    )

    signatures = raw["signatures.json"]
    signature_version = signatures.get("signatureVersion")
    _require(
        isinstance(signature_version, str) and bool(signature_version.strip()),
        "signatures.signatureVersion required",
    )
    thresholds = _validate_thresholds(signatures.get("thresholds"))
    weights = _validate_weights(signatures.get("weights"))

    category_rules: List[CategoryRule] = []
    seen_rule_ids: set[str] = set()
    for entry in signatures.get("categories", []):
        _require(isinstance(entry, dict), "signature category entries must be objects")
        category = entry.get("category")
        _require(
            isinstance(category, str) and category in categories,
            f"signature rule for unknown category {category!r}",
        )
        _require(category != fallback, "the fallback category must not carry a signature rule")
        rule_id = entry.get("ruleId")
        _require(isinstance(rule_id, str) and rule_id.strip(), "signature ruleId required")
        _require(rule_id not in seen_rule_ids, f"duplicate ruleId {rule_id!r}")
        seen_rule_ids.add(rule_id)

        exclusions: List[ExclusionRule] = []
        for excl in entry.get("exclusions", []):
            _require(isinstance(excl, dict), "exclusion entries must be objects")
            excl_id = excl.get("ruleId")
            phrase = excl.get("phrase")
            _require(isinstance(excl_id, str) and excl_id.strip(), "exclusion ruleId required")
            _require(excl_id not in seen_rule_ids, f"duplicate ruleId {excl_id!r}")
            seen_rule_ids.add(excl_id)
            _require(isinstance(phrase, str) and phrase.strip(), "exclusion phrase required")
            exclusions.append(ExclusionRule(rule_id=excl_id, phrase=phrase))

        signals = _str_list(entry.get("signals", []), f"category {category} signals")
        phrases = _str_list(entry.get("phrases", []), f"category {category} phrases")
        heading_signals = _str_list(
            entry.get("headingSignals", []), f"category {category} headingSignals"
        )
        _require(
            bool(signals or phrases or heading_signals),
            f"category rule {rule_id} must declare at least one signal or phrase",
        )
        category_rules.append(
            CategoryRule(
                rule_id=rule_id,
                category=category,
                heading_signals=heading_signals,
                signals=signals,
                phrases=phrases,
                exclusions=tuple(exclusions),
            )
        )
    _require(len(category_rules) > 0, "signatures must declare at least one category rule")
    _require(
        len({r.category for r in category_rules}) == len(category_rules),
        "one signature rule per category",
    )

    digest = hashlib.sha256(canonical_json(raw).encode("utf-8")).hexdigest()

    return DomainModule(
        module_id=module_id,
        version=version,
        digest=digest,
        description=description,
        engine_compatibility=engine_compatibility,
        signature_version=signature_version,
        categories=tuple(categories),
        fallback_category=fallback,
        category_descriptions=descriptions,
        category_rules=tuple(category_rules),
        topic_rules=tuple(topic_rules),
        market_rules=tuple(market_rules),
        personas=tuple(personas),
        thresholds=thresholds,
        weights=weights,
        fixture_names=fixture_names,
    )


@lru_cache(maxsize=8)
def load_module(module_id: str, version: str) -> DomainModule:
    """Load + validate + digest a module pack. Cached: module files are
    immutable within a release, so repeated loads are free and identical."""
    return _load_and_validate(module_id, version)


def get_active_module() -> DomainModule:
    return load_module(ACTIVE_MODULE_ID, ACTIVE_MODULE_VERSION)
