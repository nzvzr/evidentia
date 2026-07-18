"""The final versioned anchor identity algorithm (M3): ``heading-path-v1``.

Rendered citation ids are frozen into immutable report snapshots forever, so
this algorithm is governed like a public schema (PLATFORM_ARCHITECTURE.md §7):

* **Every constant below is part of the algorithm version.** The display slug
  derivation (``base36(sha1(normalized_heading_path))`` truncated to 12
  characters), the heading-path normalization rules, the duplicate/part
  suffix grammar, the deterministic collision-extension rule, the Jaccard
  inheritance threshold (0.8), the guarded-pass pair budget and the §7.3
  tie-break order may NEVER be tuned in place — any change is a new
  ``ANCHOR_ALGO_VERSION`` that coexists with this one.
* **Identity is the FULL canonical heading path, never the truncated slug.**
  The 12-character slug is a rendering of identity; every equality decision —
  duplicate grouping, heading-kept inheritance, part lineage — compares the
  complete normalized heading path (via its full SHA-1 digest). Two distinct
  headings whose truncated slugs collide are never grouped, never inherit
  from each other, and never overwrite one another: their slugs are extended
  deterministically from their own full digests until distinct.
* **Deterministic and pure.** Anchors are a function of the section's
  normalized heading path, document-order structure among identical headings,
  split-part structure, and (for inheritance) the predecessor version's
  content hashes/token sets and canonical heading paths. Database ids,
  timestamps, tenant display names, locales and LLM output never participate.
  The section ordinal alone never defines identity — it appears only in the
  specified deterministic tie-breaks and in document-order duplicate
  numbering.

Anchor grammar::

    anchor    = slug [ "-" dup ] [ ".p" part ]
    slug      = 12..31 base36 chars of sha1(normalized heading path)
                (12 normally; deterministically longer only when two DISTINCT
                canonical paths in one document share a 12-char prefix)
    dup       = 2..n   (duplicate headings, document order; 1st is bare)
    part      = 1..n   (size-bound split parts of one logical section)

Collision risk (birthday bound): the 12-char base36 slug carries
``log2(36^12) ≈ 62.04`` bits. For a document with ``n`` sections the
probability that any two DISTINCT canonical paths share a slug is
``≈ n(n-1)/2^63.04``: ``n = 1,000`` → ``≈ 1.1e-13``; ``n = 10,000`` →
``≈ 1.1e-11``. Anchor uniqueness is a per-document property, so corpus size
does not compound the exponent. Even a deliberately crafted collision (~2^31
sha1-prefix work) cannot corrupt identity: grouping and inheritance compare
full digests, colliding slugs extend deterministically (up to the full
31-char base36 digest), and a residual full-digest collision — which would
require a SHA-1 collision over normalized heading paths — still cannot
persist silently past the final uniqueness guard.

Rendered citation id = ``{document citation prefix}-{anchor}``
(e.g. ``DHP-k3f9xq81w2mz``, ``DHP-k3f9xq81w2mz.p2``) — minted by the
pipeline, opaque everywhere downstream.

Inheritance (``ANCHOR_INHERITANCE_VERSION``) is defined over *content*
(text hashes and token sets) and over the *complete canonical heading path*
(heading-kept identity), never over truncated slugs, so identities survive
future algorithm upgrades where content survives (§7.4). The specified
behaviors (§7.2) and tie-breaks (§7.3) are implemented here and pinned by
the golden fixture corpus in ``tests/golden/``.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from app.ingestion.sectionizer import SectionDraft

# --- frozen constants of heading-path-v1 (never tune in place) --------------- #
ANCHOR_ALGO_VERSION = "heading-path-v1"
ANCHOR_INHERITANCE_VERSION = "content-match-v1"
SLUG_CHARS = 12
# The full sha1 digest rendered in base36 is at most 31 chars; slugs extend in
# these steps (own-digest-derived) when distinct canonical paths collide.
SLUG_FULL_CHARS = 31
SLUG_EXTEND_STEP = 4
JACCARD_INHERIT_THRESHOLD = 0.8
# The guarded (Jaccard) pass is O(disappeared × unmatched). This budget keeps
# a pathological revision bounded; when exceeded, the guarded pass is skipped
# deterministically (exact-hash inheritance still runs) and new anchors are
# minted — safe (never a wrong inheritance), and a version property, not a
# tunable.
GUARDED_PASS_MAX_PAIRS = 250_000

_HEADING_WS = re.compile(r"\s+")
_PATH_SEPARATOR = "\x1f"  # unit separator: cannot appear in normalized titles
_B36_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"

# Anchor decision vocabulary (persisted in anchor_provenance).
DECISION_MINTED = "minted"
DECISION_UNCHANGED = "unchanged"           # same anchor, same content hash
DECISION_HEADING_KEPT = "heading-kept"     # same anchor (heading path), edited content
DECISION_REATTACHED = "reattached-exact"   # duplicate renumbering undone by exact hash
DECISION_INHERITED_EXACT = "inherited-exact"      # disappeared anchor, identical content
DECISION_INHERITED_SIMILAR = "inherited-similar"  # disappeared anchor, Jaccard >= 0.8
DECISION_SPLIT_LINEAGE = "split-lineage"   # part of a previously-unsplit anchor

# --- the FROZEN anchor-provenance contract (part of the algorithm version) --- #
# The complete allowed decision vocabulary. Any other value is malformed.
ANCHOR_DECISIONS = frozenset(
    {
        DECISION_MINTED,
        DECISION_UNCHANGED,
        DECISION_HEADING_KEPT,
        DECISION_REATTACHED,
        DECISION_INHERITED_EXACT,
        DECISION_INHERITED_SIMILAR,
        DECISION_SPLIT_LINEAGE,
    }
)
# Decisions whose identity is carried over from a predecessor anchor: they MUST
# name the anchor they inherited from. Every non-minted decision is a lineage
# decision (unchanged/heading-kept/reattached keep their own prior anchor;
# inherited-*/split-lineage adopt a disappeared or unsplit prior anchor).
ANCHOR_INHERITED_DECISIONS = ANCHOR_DECISIONS - {DECISION_MINTED}
# Only a freshly minted identity forbids an inherited-from anchor.
ANCHOR_MINTED_DECISIONS = frozenset({DECISION_MINTED})
# Decisions that carry a numeric similarity (the disappeared-anchor pass): exact
# match records EXACTLY 1.0, guarded match records its Jaccard score, which by
# construction satisfies JACCARD_INHERIT_THRESHOLD <= s <= 1.0. No other
# decision may carry `similarity`.
ANCHOR_SIMILARITY_DECISIONS = frozenset({DECISION_INHERITED_EXACT, DECISION_INHERITED_SIMILAR})
# Decisions that RETAIN one permanent anchor as the section's current identity:
# unchanged/heading-kept/reattached keep the section's own prior anchor, and the
# disappeared-anchor pass ADOPTS the inherited anchor as the current one — in
# every case `inheritedFrom` IS the current anchor_id, verbatim. Only
# split-lineage derives a DIFFERENT current anchor (the parent's first part).
ANCHOR_SELF_LINEAGE_DECISIONS = ANCHOR_INHERITED_DECISIONS - {DECISION_SPLIT_LINEAGE}
# The one split-derived relationship the algorithm ever persists (§7.2): a
# previously-unsplit section that grew past the size bound keeps its citation
# lineage on part 1 — the current anchor is EXACTLY `{parent}.p1`.
_SPLIT_FIRST_PART_SUFFIX = ".p1"

# The exact provenance key schema. Extra keys fail closed (immutable-artifact
# integrity): a persisted provenance blob is only valid when its keys are
# exactly those the decision implies.
_PROV_BASE_KEYS = frozenset({"algo", "inheritance", "decision"})
_PROV_INHERITED_FROM_KEY = "inheritedFrom"
_PROV_SIMILARITY_KEY = "similarity"


def validate_anchor_provenance(
    provenance: object, *, anchor_id: str, algo: str, inheritance: str
) -> Optional[str]:
    """Validate one persisted ``anchor_provenance`` blob against the FROZEN
    anchor contract, the section's CURRENT ``anchor_id`` and the resolved
    target's ``(algo, inheritance)`` versions.

    Returns ``None`` when the blob is a canonical, fully consistent provenance
    for a supported anchor decision; otherwise a stable typed reason code. Pure
    and total — it never raises. Beyond field shape, the DECISION SEMANTICS of
    ``assign_anchors`` are enforced (all load-bearing):

    * ``algo`` equals the target anchor algorithm version;
    * ``inheritance`` equals the target inheritance algorithm version;
    * ``decision`` is in the frozen decision vocabulary;
    * minted: no ``inheritedFrom``, no ``similarity`` — a fresh identity has no
      predecessor lineage;
    * unchanged / heading-kept / reattached-exact / inherited-exact /
      inherited-similar: ``inheritedFrom`` is required and must equal the
      current ``anchor_id`` verbatim — these decisions retain (or adopt as
      current) exactly one permanent anchor, so an unrelated predecessor is a
      lineage forgery;
    * split-lineage: ``inheritedFrom`` (the unsplit parent) is required, must
      itself parse under THE canonical anchor grammar (``ANCHOR_GRAMMAR_RE``:
      bare slug or ``slug-N`` with N >= 2, canonical decimal, no leading
      zeros, no part suffix), and the current anchor must be EXACTLY
      ``{parent}.p1`` — any other parent/child relationship is impossible
      under §7.2. Malformed parents reject before the relationship comparison.
      (For the self-lineage decisions above, ``inheritedFrom`` equals the
      current anchor, whose canonical grammar the caller checks — so every
      accepted lineage anchor is canonical.);
    * ``similarity`` appears exactly for the similarity-bearing decisions:
      inherited-exact requires EXACTLY 1.0 (the frozen exact-match value);
      inherited-similar requires a finite number with
      ``JACCARD_INHERIT_THRESHOLD <= s <= 1.0`` — a below-threshold value can
      never have been produced by the frozen algorithm;
    * no extra keys beyond the schema the decision implies.
    """
    if not isinstance(provenance, dict):
        return "anchor_provenance_missing"
    if provenance.get("algo") != algo:
        return "anchor_algo_mismatch"
    if provenance.get("inheritance") != inheritance:
        return "anchor_inheritance_mismatch"
    decision = provenance.get("decision")
    if decision not in ANCHOR_DECISIONS:
        return "anchor_decision_invalid"

    allowed = set(_PROV_BASE_KEYS)
    has_inherited = _PROV_INHERITED_FROM_KEY in provenance
    inherited_from = provenance.get(_PROV_INHERITED_FROM_KEY)
    if decision in ANCHOR_MINTED_DECISIONS:
        if has_inherited:
            return "anchor_minted_has_inherited_from"
    else:
        if not has_inherited or not isinstance(inherited_from, str) or not inherited_from:
            return "anchor_inherited_missing_from"
        allowed.add(_PROV_INHERITED_FROM_KEY)
        if decision in ANCHOR_SELF_LINEAGE_DECISIONS:
            # The retained/adopted permanent anchor IS the current identity.
            if inherited_from != anchor_id:
                return "anchor_lineage_mismatch"
        else:  # split-lineage: current anchor == "{parent}.p1", parent part-free
            # Parse the parent through THE canonical grammar FIRST: a malformed
            # duplicate suffix ("-0"/"-1"/"-01"/…) or a part-suffixed parent
            # rejects before any relationship comparison.
            parent_slug, _parent_dup, parent_part = _parse_anchor(inherited_from)
            if parent_slug == "\x00" or parent_part is not None:
                return "anchor_split_lineage_invalid"
            if anchor_id != f"{inherited_from}{_SPLIT_FIRST_PART_SUFFIX}":
                return "anchor_split_lineage_invalid"

    if _PROV_SIMILARITY_KEY in provenance:
        if decision not in ANCHOR_SIMILARITY_DECISIONS:
            return "anchor_similarity_unexpected"
        similarity = provenance.get(_PROV_SIMILARITY_KEY)
        if (
            isinstance(similarity, bool)
            or not isinstance(similarity, (int, float))
            or not math.isfinite(float(similarity))
            or not (0.0 <= float(similarity) <= 1.0)
        ):
            return "anchor_similarity_invalid"
        if decision == DECISION_INHERITED_EXACT and float(similarity) != 1.0:
            # The frozen persisted representation of an exact content match.
            return "anchor_similarity_not_exact"
        if (
            decision == DECISION_INHERITED_SIMILAR
            and float(similarity) < JACCARD_INHERIT_THRESHOLD
        ):
            # The guarded pass can never inherit below the frozen threshold.
            return "anchor_similarity_below_threshold"
        allowed.add(_PROV_SIMILARITY_KEY)
    elif decision in ANCHOR_SIMILARITY_DECISIONS:
        return "anchor_similarity_missing"

    if set(provenance) - allowed:
        return "anchor_provenance_extra_field"
    return None


def _base36(data: bytes) -> str:
    value = int.from_bytes(data, "big")
    if value == 0:
        return "0"
    out: List[str] = []
    while value:
        value, rem = divmod(value, 36)
        out.append(_B36_ALPHABET[rem])
    return "".join(reversed(out))


def normalize_heading_path(heading_path: Sequence[str]) -> str:
    """Frozen normalization: per element NFC -> casefold -> whitespace collapse
    -> strip; elements joined with a separator that cannot occur in them."""
    parts = []
    for element in heading_path:
        text = unicodedata.normalize("NFC", str(element)).casefold()
        text = _HEADING_WS.sub(" ", text).strip()
        parts.append(text)
    return _PATH_SEPARATOR.join(parts)


def heading_path_digest(heading_path: Sequence[str]) -> str:
    """The COMPLETE canonical heading identity: full sha1 hex over the
    normalized heading path. Every identity comparison (duplicate grouping,
    heading-kept inheritance, part lineage) uses this, never the slug."""
    normalized = normalize_heading_path(heading_path)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _digest_base36(digest_hex: str) -> str:
    """The full digest rendered in base36, zero-padded to a fixed width so
    prefix comparisons are well defined."""
    return _base36(bytes.fromhex(digest_hex)).rjust(SLUG_FULL_CHARS, "0")


def heading_slug(heading_path: Sequence[str]) -> str:
    """``base36(sha1(normalized_heading_path))[:12]`` — the DISPLAY slug.
    Never proof of identity: two distinct canonical paths may (with ~2^-62
    per-pair probability) share it; `assign_anchors` resolves that by
    deterministic own-digest extension."""
    return _digest_base36(heading_path_digest(heading_path))[:SLUG_CHARS]


def _resolve_slugs(
    digests: Sequence[str],
    foreign_bases: Optional[Dict[str, set]] = None,
) -> Dict[str, str]:
    """digest -> slug for one document, deterministically.

    Every digest starts at the 12-char prefix of its own full base36
    rendering. Exactly the digests in conflict extend (in fixed steps, each
    from its OWN digest) until conflict-free or fully expanded; a heading in
    no conflict always keeps its plain 12-char slug, so unrelated headings
    can never perturb each other. Two conflicts exist:

    * intra-document: two DISTINCT digests share a slug prefix — grouping
      them would corrupt duplicate numbering;
    * cross-version: the slug equals a PRIOR anchor base whose canonical
      heading identity differs (``foreign_bases``: prior base -> the set of
      heading digests that used it, None for unknown) — minting it would
      textually resurrect a retired anchor for an unrelated section, which a
      citation into the predecessor version would then mis-resolve.
    """
    foreign = foreign_bases or {}
    unique = sorted(set(digests))
    full = {d: _digest_base36(d) for d in unique}
    length = {d: SLUG_CHARS for d in unique}
    while True:
        groups: Dict[str, List[str]] = {}
        for d in unique:
            groups.setdefault(full[d][: length[d]], []).append(d)
        need_extend: set[str] = set()
        for ds in groups.values():
            if len(ds) > 1:
                need_extend.update(ds)
        for d in unique:
            owners = foreign.get(full[d][: length[d]])
            if owners and any(owner != d for owner in owners):
                need_extend.add(d)
        if not need_extend:
            break
        progressed = False
        for d in need_extend:
            if length[d] < SLUG_FULL_CHARS:
                length[d] = min(length[d] + SLUG_EXTEND_STEP, SLUG_FULL_CHARS)
                progressed = True
        if not progressed:
            # Full base36 renderings equal => sha1(normalized path) equal.
            # Under this algorithm version the digest IS canonical identity,
            # so such inputs are the same heading by definition; distinct
            # digests can never reach here.
            break
    return {d: full[d][: length[d]] for d in unique}


def _compose(slug: str, dup_index: int, part: Optional[int]) -> str:
    anchor = slug if dup_index <= 1 else f"{slug}-{dup_index}"
    if part is not None:
        anchor = f"{anchor}.p{part}"
    return anchor


def jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    set_a, set_b = set(a), set(b)
    if not set_a and not set_b:
        return 0.0
    union = len(set_a | set_b)
    return len(set_a & set_b) / union if union else 0.0


# --------------------------------------------------------------------------- #
# inputs / outputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PriorSection:
    """The inheritance-relevant projection of a predecessor version's section.
    Content + canonical heading identity only — no database ids, no
    timestamps. ``heading_path`` feeds the COMPLETE canonical identity used
    by heading-kept inheritance; without it a prior can only donate its
    anchor through content matching (fail-safe)."""

    anchor_id: str
    text_sha256: str
    token_set: Tuple[str, ...]
    ordinal: int
    heading_path: Tuple[str, ...] = ()


@dataclass
class AnchorAssignment:
    """One draft's final identity plus the provenance that reproduces it."""

    anchor_id: str
    decision: str
    inherited_from: Optional[str] = None
    similarity: Optional[float] = None

    def provenance(self) -> Dict[str, object]:
        data: Dict[str, object] = {
            "algo": ANCHOR_ALGO_VERSION,
            "inheritance": ANCHOR_INHERITANCE_VERSION,
            "decision": self.decision,
        }
        if self.inherited_from is not None:
            data["inheritedFrom"] = self.inherited_from
        if self.similarity is not None:
            data["similarity"] = round(self.similarity, 4)
        return data


@dataclass
class _Logical:
    """One logical section = consecutive drafts sharing a heading occurrence
    (split parts stay together)."""

    digest: str  # full canonical heading identity (never the slug)
    draft_indexes: List[int] = field(default_factory=list)


def _group_logical(drafts: Sequence[SectionDraft]) -> List[_Logical]:
    logicals: List[_Logical] = []
    for index, draft in enumerate(drafts):
        part = draft.meta.get("split_part")
        if part is not None and int(part) > 1 and logicals:
            logicals[-1].draft_indexes.append(index)
            continue
        logicals.append(
            _Logical(digest=heading_path_digest(draft.heading_path), draft_indexes=[index])
        )
    return logicals


def assign_anchors(
    drafts: Sequence[SectionDraft],
    prior_sections: Sequence[PriorSection] = (),
) -> List[AnchorAssignment]:
    """Assign final anchors to an ordered draft list, inheriting from the
    predecessor version's sections where the frozen rules permit.

    Deterministic: identical inputs always produce identical assignments.
    One prior anchor is inherited by at most one draft; one draft inherits at
    most one prior anchor; every collision and tie is resolved by the §7.3
    order. Heading-identity inheritance compares COMPLETE canonical heading
    paths (full digests) — a truncated-slug coincidence can never group two
    distinct headings, transfer an anchor between them, or fail silently.
    Raises ValueError on an (impossible by construction) anchor collision
    rather than persisting a corrupt identity set.
    """
    prior_by_anchor: Dict[str, PriorSection] = {p.anchor_id: p for p in prior_sections}
    # Complete canonical identity of each prior anchor's heading (None when
    # the prior carries no heading path — then it can never heading-match).
    prior_heading_digest: Dict[str, Optional[str]] = {
        p.anchor_id: (heading_path_digest(p.heading_path) if p.heading_path else None)
        for p in prior_sections
    }

    logicals = _group_logical(drafts)
    # Prior anchor bases and the canonical identities that own them: a minted
    # slug may never textually coincide with a retired anchor of a DIFFERENT
    # heading (None = identity unknown, treated as foreign — fail safe).
    foreign_bases: Dict[str, set] = {}
    for anchor in prior_by_anchor:
        base, _dup, _part = _parse_anchor(anchor)
        foreign_bases.setdefault(base, set()).add(prior_heading_digest[anchor])
    slug_by_digest = _resolve_slugs(
        [logical.digest for logical in logicals], foreign_bases
    )

    # -- structural assignment: duplicate numbering + exact re-attachment ---- #
    # Per CANONICAL-IDENTITY group, unchanged duplicates re-attach to their old
    # anchors by exact content hash BEFORE document-order renumbering is
    # accepted (§7.2 "insertion before existing duplicates").
    by_digest: Dict[str, List[int]] = {}
    for li, logical in enumerate(logicals):
        by_digest.setdefault(logical.digest, []).append(li)

    logical_anchor: Dict[int, str] = {}          # logical index -> anchor (no part suffix)
    logical_decision: Dict[int, str] = {}
    claimed_prior: set[str] = set()

    def _logical_hash(logical: _Logical) -> str:
        """Content hash of the whole logical section (parts joined) — what a
        previously-identical unsplit/split-alike occurrence would match."""
        if len(logical.draft_indexes) == 1:
            return drafts[logical.draft_indexes[0]].text_sha256
        joined = "\n\n".join(drafts[i].text for i in logical.draft_indexes)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    for digest, logical_indexes in by_digest.items():
        slug = slug_by_digest[digest]
        # Prior anchors of this COMPLETE canonical heading identity, keyed by
        # dup index (bare = 1). Only unsuffixed-or-dup anchors participate;
        # part anchors are matched at the part level below. Slug equality is
        # deliberately never consulted: a truncated-slug coincidence between
        # different canonical paths must never join this group.
        prior_group: Dict[int, PriorSection] = {}
        for anchor, prior in prior_by_anchor.items():
            if prior_heading_digest[anchor] != digest:
                continue
            _base, dup, part = _parse_anchor(anchor)
            if part is None:
                prior_group[dup] = prior

        # Exact re-attachment pass (document order): an unchanged occurrence
        # keeps its old dup index even if occurrences shifted around it.
        assigned_dups: set[int] = set()
        pending: List[int] = []
        for li in logical_indexes:
            content_hash = _logical_hash(logicals[li])
            match_dup: Optional[int] = None
            for dup in sorted(prior_group):
                if dup in assigned_dups:
                    continue
                if prior_group[dup].text_sha256 == content_hash:
                    match_dup = dup
                    break
            if match_dup is not None:
                assigned_dups.add(match_dup)
                # Keep the prior's anchor STRING verbatim: it is the identity
                # token (its slug may be an extended form minted earlier).
                anchor = prior_group[match_dup].anchor_id
                logical_anchor[li] = anchor
                logical_decision[li] = (
                    DECISION_UNCHANGED if match_dup == _occurrence_index(logical_indexes, li) else DECISION_REATTACHED
                )
                claimed_prior.add(anchor)
            else:
                pending.append(li)

        # Remaining occurrences take the lowest free dup indices in document
        # order — the deterministic renumbering the exact pass protects.
        next_free = 1
        for li in pending:
            while next_free in assigned_dups:
                next_free += 1
            assigned_dups.add(next_free)
            prior = prior_group.get(next_free)
            if prior is not None and prior.anchor_id not in claimed_prior:
                # Same COMPLETE heading path (and dup position) as before:
                # identity is the heading path, so the anchor is kept across
                # content edits.
                logical_anchor[li] = prior.anchor_id
                logical_decision[li] = (
                    DECISION_UNCHANGED
                    if prior.text_sha256 == _logical_hash(logicals[li])
                    else DECISION_HEADING_KEPT
                )
                claimed_prior.add(prior.anchor_id)
            else:
                logical_anchor[li] = _compose(slug, next_free, None)
                logical_decision[li] = DECISION_MINTED

    # -- expand logicals into per-draft assignments (split parts) ------------ #
    assignments: Dict[int, AnchorAssignment] = {}
    for li, logical in enumerate(logicals):
        base_anchor = logical_anchor[li]
        decision = logical_decision[li]
        if len(logical.draft_indexes) == 1:
            di = logical.draft_indexes[0]
            inherited = base_anchor if decision in (
                DECISION_UNCHANGED, DECISION_HEADING_KEPT, DECISION_REATTACHED
            ) else None
            assignments[di] = AnchorAssignment(
                anchor_id=base_anchor, decision=decision, inherited_from=inherited
            )
            continue
        for part_no, di in enumerate(logical.draft_indexes, start=1):
            part_anchor = f"{base_anchor}.p{part_no}"
            part_prior = prior_by_anchor.get(part_anchor)
            if part_prior is not None and prior_heading_digest[part_anchor] == logical.digest:
                part_decision = (
                    DECISION_UNCHANGED
                    if part_prior.text_sha256 == drafts[di].text_sha256
                    else DECISION_HEADING_KEPT
                )
                claimed_prior.add(part_anchor)
                assignments[di] = AnchorAssignment(
                    anchor_id=part_anchor, decision=part_decision, inherited_from=part_anchor
                )
            elif (
                part_no == 1
                and base_anchor in prior_by_anchor
                and prior_heading_digest[base_anchor] == logical.digest
            ):
                # A previously-unsplit section that grew past the size bound:
                # .p1 carries the original anchor's citation lineage (§7.2).
                claimed_prior.add(base_anchor)
                assignments[di] = AnchorAssignment(
                    anchor_id=part_anchor,
                    decision=DECISION_SPLIT_LINEAGE,
                    inherited_from=base_anchor,
                )
            else:
                assignments[di] = AnchorAssignment(anchor_id=part_anchor, decision=DECISION_MINTED)

    # -- disappeared-anchor inheritance (rename / rename+split) -------------- #
    # Candidates: prior anchors nobody claimed x drafts whose anchor was
    # freshly minted. Exact hash first, then guarded Jaccard; §7.3 tie-break.
    disappeared = {
        anchor: prior for anchor, prior in prior_by_anchor.items() if anchor not in claimed_prior
    }
    minted_drafts = [di for di, a in assignments.items() if a.decision == DECISION_MINTED]

    if disappeared and minted_drafts:
        run_guarded = len(disappeared) * len(minted_drafts) <= GUARDED_PASS_MAX_PAIRS
        candidates: List[Tuple[bool, float, int, str, int]] = []
        for di in minted_drafts:
            draft = drafts[di]
            for anchor, prior in disappeared.items():
                exact = draft.text_sha256 == prior.text_sha256
                if exact:
                    similarity = 1.0
                elif run_guarded:
                    similarity = jaccard(draft.token_set, prior.token_set)
                    if similarity < JACCARD_INHERIT_THRESHOLD:
                        continue
                else:
                    continue
                candidates.append((exact, similarity, abs(draft.ordinal - prior.ordinal), anchor, di))

        # §7.3: exact hash beats any similarity; then highest Jaccard; then
        # nearest document order; then lowest anchor id; finally draft order.
        candidates.sort(key=lambda c: (not c[0], -c[1], c[2], c[3], c[4]))
        used_anchors: set[str] = set()
        used_drafts: set[int] = set()
        for exact, similarity, _delta, anchor, di in candidates:
            if anchor in used_anchors or di in used_drafts:
                continue
            used_anchors.add(anchor)
            used_drafts.add(di)
            assignments[di] = AnchorAssignment(
                anchor_id=anchor,
                decision=DECISION_INHERITED_EXACT if exact else DECISION_INHERITED_SIMILAR,
                inherited_from=anchor,
                similarity=similarity,
            )

    ordered = [assignments[i] for i in range(len(drafts))]

    # Collision guard: identity corruption must never persist silently.
    seen: set[str] = set()
    for assignment in ordered:
        if assignment.anchor_id in seen:
            raise ValueError(f"anchor collision: {assignment.anchor_id!r}")
        seen.add(assignment.anchor_id)
    return ordered


def _occurrence_index(logical_indexes: List[int], li: int) -> int:
    """1-based document-order occurrence index of `li` within its identity group."""
    return logical_indexes.index(li) + 1


# THE canonical permanent-anchor grammar — the single definition every
# consumer (inheritance parsing, provenance validation, eligibility) shares:
#
#     anchor = slug [ "-" dup ] [ ".p" part ]
#     slug   = SLUG_CHARS..SLUG_FULL_CHARS base36 chars (12 minimum; longer
#              only via the deterministic own-digest extension)
#     dup    = integer >= 2, canonical decimal, no leading zeros — the FIRST
#              occurrence of a heading is always the BARE slug, so "-0" and
#              "-1" are unrepresentable, as is any zero-padded form
#     part   = integer >= 1, canonical decimal, no leading zeros
#
# `_compose` can only emit this shape (dup suffixes start at 2, parts at 1,
# Python int formatting never pads), so the grammar is a parser-side guarantee,
# not a new constraint on generation.
# STRICT ASCII digit classes only: Python's `\d` matches Unicode decimal
# digits (e.g. "٢", "２"), which int() would then silently convert — a stored
# identifier must never be repaired or normalized, so the grammar spells out
# [0-9] explicitly and the parser matches the ENTIRE string via fullmatch()
# (a bare `$` may match before a trailing newline).
_CANONICAL_DUP = r"(?:[2-9]|[1-9][0-9]+)"
_CANONICAL_PART = r"(?:[1-9][0-9]*)"
_GRAMMAR_CACHE: Dict[Tuple[int, int], "re.Pattern[str]"] = {}


def _anchor_grammar_re() -> "re.Pattern[str]":
    """The compiled canonical grammar for the CURRENT slug bounds. The slug
    width is read at call time so the parser stays in lockstep with the
    algorithm parameters (collision tests shrink SLUG_CHARS deliberately);
    under the frozen production constants the pattern is a fixed 12..31.
    Anchored with \\A/\\Z and always applied via fullmatch(): no prefix,
    suffix, trailing-newline or whitespace laxness."""
    key = (SLUG_CHARS, SLUG_FULL_CHARS)
    pattern = _GRAMMAR_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(
            rf"\A([0-9a-z]{{{key[0]},{key[1]}}})"
            rf"(?:-({_CANONICAL_DUP}))?(?:\.p({_CANONICAL_PART}))?\Z"
        )
        _GRAMMAR_CACHE[key] = pattern
    return pattern


# The frozen production grammar (12..31 slug), importable for reference.
ANCHOR_GRAMMAR_RE = _anchor_grammar_re()


def is_canonical_anchor(anchor: object) -> bool:
    """True iff ``anchor`` is a well-formed PERMANENT anchor under the frozen
    canonical grammar, matched against the ENTIRE string (fullmatch, ASCII
    digits only). Transitional ordinal ids (shorter than 12 chars), every
    non-canonical suffix form ("-0", "-1", "-01", ".p0", ".p01", …), Unicode
    digits and any leading/trailing character (including "\\n") never match."""
    return (
        isinstance(anchor, str)
        and _anchor_grammar_re().fullmatch(anchor) is not None
    )


def _parse_anchor(anchor: str) -> Tuple[str, int, Optional[int]]:
    """anchor -> (slug, dup index (bare = 1), part or None), accepting ONLY
    the canonical grammar above — the whole string, exactly (fullmatch; the
    parser validates an already-canonical stored identifier and never strips,
    folds or otherwise repairs one). Anything else — transitional ids, which
    never reach inheritance, and malformed forms like "-0"/"-1"/"-01"/".p0"/
    Unicode digits/trailing newline, which no generator ever emitted — maps to
    a never-matching slug."""
    match = _anchor_grammar_re().fullmatch(anchor)
    if not match:
        return ("\x00", 1, None)
    slug, dup, part = match.groups()
    return (slug, int(dup) if dup else 1, int(part) if part else None)


# --------------------------------------------------------------------------- #
# citation prefix derivation (documents.citation_prefix)
# --------------------------------------------------------------------------- #

# Frozen with the algorithm version: 3–5 uppercase chars from the title's
# significant initials, consonant-padded; tenant-unique with numeric suffix on
# collision; immutable thereafter — the prefix is identity, not description.
_PREFIX_STOPWORDS = frozenset(
    {"a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "at", "by", "with"}
)
_CONSONANTS = frozenset("BCDFGHJKLMNPQRSTVWXYZ")
PREFIX_MIN_CHARS = 3
PREFIX_MAX_CHARS = 5
# The widest prefix the schema stores (documents.citation_prefix): a 5-char
# base plus a numeric suffix up to 7 digits — capacity for far beyond any
# configured tenant document quota (suffixes are minted through quota + 1).
PREFIX_COLUMN_CHARS = 12
# Default candidate capacity when a caller does not pass the configured tenant
# quota explicitly. Matches the platform default `evidentia_tenant_max_documents`
# so allocation can never exhaust before the documented quota does.
DEFAULT_PREFIX_CANDIDATES = 500


def derive_citation_prefix(title: str) -> str:
    """Deterministic base prefix from a document title
    (e.g. "Data Handling Policy" -> "DHP"). Collision suffixing is the
    caller's job (allocation is a tenant-scoped, DB-arbitrated concern)."""
    ascii_title = (
        unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii")
    )
    words = [w for w in re.findall(r"[A-Za-z0-9]+", ascii_title) if w.lower() not in _PREFIX_STOPWORDS]
    if not words:
        words = re.findall(r"[A-Za-z0-9]+", ascii_title)
    if not words:
        return "DOC"  # a title with no usable characters at all
    prefix = "".join(w[0] for w in words[:PREFIX_MAX_CHARS]).upper()
    if len(prefix) < PREFIX_MIN_CHARS:
        pool = "".join(words).upper()
        for ch in pool[1:]:
            if len(prefix) >= PREFIX_MIN_CHARS:
                break
            if ch in _CONSONANTS:
                prefix += ch
        while len(prefix) < PREFIX_MIN_CHARS:
            prefix += "X"
    return prefix[:PREFIX_MAX_CHARS]


def prefix_candidates(title: str, limit: int = DEFAULT_PREFIX_CANDIDATES):
    """The deterministic candidate sequence for tenant-unique allocation:
    base, base2, base3, … (the DB unique index arbitrates).

    Yields ``limit + 1`` candidates (the bare base plus numeric suffixes
    2..limit+1), so passing the configured tenant document quota as ``limit``
    guarantees at least quota-many candidates even when EVERY document in the
    tenant falls back to the same base (empty, punctuation-only or non-Latin
    titles all derive "DOC"). Candidates that would overflow the schema's
    prefix column are never yielded; with a 5-char base that admits suffixes
    up to 7 digits, far beyond any supported quota."""
    base = derive_citation_prefix(title)
    if len(base) <= PREFIX_COLUMN_CHARS:
        yield base
    for n in range(2, limit + 2):
        candidate = f"{base}{n}"
        if len(candidate) > PREFIX_COLUMN_CHARS:
            return
        yield candidate


def render_citation_id(prefix: str, anchor_id: str) -> str:
    return f"{prefix}-{anchor_id}"
