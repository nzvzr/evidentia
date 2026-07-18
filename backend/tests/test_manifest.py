"""M3 — the final deterministic manifest: canonical serialization, retry
reproducibility, and sensitivity to every load-bearing input."""

from __future__ import annotations

import copy
import re

from app.ingestion.manifest import (
    MANIFEST_VERSION,
    build_manifest,
    manifest_sha256,
    section_manifest_entry,
)


def _entry(**overrides):
    base = dict(
        ordinal=0,
        anchor_id="k3f9x",
        citation_id="DHP-k3f9x",
        text_sha256="a" * 64,
        heading_path=["Policy", "Data Residency"],
        depth=2,
        char_count=240,
        has_tables=False,
        has_omitted_content=False,
        category="Compliance",
        topics=["Residency"],
        market_flags=["EMEA"],
        injection_flags=[],
        keywords=["residency", "sovereignty"],
        persona_affinity={"compliance": 0.5},
        matched_rules=["compliance.category.compliance"],
        classification_signature="b" * 64,
        anchor_provenance={
            "algo": "heading-path-v1",
            "inheritance": "content-match-v1",
            "decision": "minted",
        },
    )
    base.update(overrides)
    return section_manifest_entry(**base)


def _manifest(sections=None, engine=None):
    return build_manifest(
        content_sha256="c" * 64,
        extracted_sha256="d" * 64,
        citation_prefix="DHP",
        engine_versions=engine
        or {
            "parser": "m2.1",
            "anchorAlgo": "heading-path-v1",
            "classifier": "m3.1",
            "module": {"id": "compliance", "version": "1.0.0", "digest": "e" * 64},
        },
        sections=sections if sections is not None else [_entry()],
    )


class TestManifest:
    def test_deterministic_and_retry_stable(self):
        assert manifest_sha256(_manifest()) == manifest_sha256(_manifest())

    def test_key_order_does_not_matter(self):
        """Canonical serialization: semantically equal dicts hash equal."""
        manifest = _manifest()
        shuffled = {k: manifest[k] for k in reversed(list(manifest))}
        assert manifest_sha256(manifest) == manifest_sha256(shuffled)

    def test_changed_section_changes_manifest(self):
        base = manifest_sha256(_manifest())
        changed = manifest_sha256(_manifest(sections=[_entry(text_sha256="f" * 64)]))
        assert base != changed

    def test_changed_anchor_changes_manifest(self):
        base = manifest_sha256(_manifest())
        changed = manifest_sha256(
            _manifest(sections=[_entry(anchor_id="zzzzz", citation_id="DHP-zzzzz")])
        )
        assert base != changed

    def test_changed_classification_changes_manifest(self):
        base = manifest_sha256(_manifest())
        changed = manifest_sha256(_manifest(sections=[_entry(category="Security")]))
        assert base != changed

    def test_anchor_provenance_is_bound_into_the_digest(self):
        """Anchor provenance is part of the immutable artifact: changing the
        decision, the inherited-from lineage or the similarity — with every
        other field identical — must change the manifest digest."""
        base = manifest_sha256(_manifest())
        prov_changed = manifest_sha256(
            _manifest(
                sections=[
                    _entry(
                        anchor_provenance={
                            "algo": "heading-path-v1",
                            "inheritance": "content-match-v1",
                            "decision": "inherited-similar",
                            "inheritedFrom": "k3f9x",
                            "similarity": 0.87,
                        }
                    )
                ]
            )
        )
        assert base != prov_changed
        # even a lone similarity tweak (everything else identical) moves it
        similar = _entry(
            anchor_provenance={
                "algo": "heading-path-v1",
                "inheritance": "content-match-v1",
                "decision": "inherited-similar",
                "inheritedFrom": "k3f9x",
                "similarity": 0.87,
            }
        )
        similar_2 = _entry(
            anchor_provenance={
                "algo": "heading-path-v1",
                "inheritance": "content-match-v1",
                "decision": "inherited-similar",
                "inheritedFrom": "k3f9x",
                "similarity": 0.86,
            }
        )
        assert manifest_sha256(_manifest(sections=[similar])) != manifest_sha256(
            _manifest(sections=[similar_2])
        )

    def test_section_entry_requires_provenance(self):
        """A manifest section entry cannot be built without provenance — the
        binding is not optional."""
        import pytest

        with pytest.raises(TypeError):
            section_manifest_entry(
                ordinal=0,
                anchor_id="k3f9x",
                citation_id="DHP-k3f9x",
                text_sha256="a" * 64,
                heading_path=["Policy"],
                depth=1,
                char_count=10,
                has_tables=False,
                has_omitted_content=False,
                category="General",
                topics=[],
                market_flags=[],
                injection_flags=[],
                keywords=[],
                persona_affinity={},
                matched_rules=[],
                classification_signature="b" * 64,
            )

    def test_changed_engine_or_module_version_changes_manifest(self):
        base = manifest_sha256(_manifest())
        engine = {
            "parser": "m2.1",
            "anchorAlgo": "heading-path-v2",  # load-bearing version bump
            "classifier": "m3.1",
            "module": {"id": "compliance", "version": "1.0.0", "digest": "e" * 64},
        }
        assert base != manifest_sha256(_manifest(engine=engine))
        engine2 = copy.deepcopy(engine)
        engine2["anchorAlgo"] = "heading-path-v1"
        engine2["module"]["version"] = "1.1.0"
        assert base != manifest_sha256(_manifest(engine=engine2))

    def test_section_order_changes_manifest(self):
        two = [_entry(), _entry(ordinal=1, anchor_id="aaaaa", citation_id="DHP-aaaaa")]
        assert manifest_sha256(_manifest(sections=two)) != manifest_sha256(
            _manifest(sections=list(reversed(two)))
        )

    def test_no_timestamps_or_db_ids_enter_the_digest(self):
        """The manifest is built exclusively from algorithm-derived fields —
        no field looks like a row id or a timestamp."""
        manifest = _manifest()
        import json

        dump = json.dumps(manifest)
        assert "createdAt" not in dump and "updatedAt" not in dump
        assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", dump)
        assert not re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", dump
        )

    def test_manifest_version_constant(self):
        assert MANIFEST_VERSION == "m3.1"
        assert _manifest()["manifestVersion"] == "m3.1"
