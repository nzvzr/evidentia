from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import app.agents.orchestrator as orchestrator_module
from app.agents.orchestrator import run_pipeline_ex
from app.agents.section_provider import (
    RetrievedEvidence,
    SourceVersionSnapshot,
    TenantCorpusProvider,
    TenantRetrievalConfig,
)
from app.claims.engine import accepted_claim_risks, run_claim_engine
from app.claims.gate import REASON_FOREIGN_EVIDENCE, decide_claim
from app.claims.matchers import EvidenceContext, evaluate_matcher, normalize_text
from app.claims.patterns import PatternValidationError, _load_release, load_active_claim_patterns
from app.contracts import ClaimCandidate
from app.core.config import get_settings
from app.eval.claim_metrics import claim_fixture_metrics, compare_pattern_versions
from app.ingestion.finalization_target import build_finalization_target
from app.modules.loader import get_active_module
from app.services.llm import LLMCallResult

MODULE_DIR = (
    Path(__file__).resolve().parents[1]
    / "app" / "modules" / "compliance" / "claim-patterns" / "1.0.0"
)


def provider_for(text: str, citation: str = "FIX-aaaaaaaaaaaa") -> TenantCorpusProvider:
    source = SourceVersionSnapshot(
        document_id="doc-1", document_version_id="version-1", version_no=1,
        document_title="Control policy", original_filename="policy.md",
        manifest_sha256="a" * 64, finalization_target_digest="cft1:" + "b" * 64,
        parser_version="1", anchor_algo_version="heading-path-v1", position=0,
    )
    evidence = RetrievedEvidence(
        company_id="company-1", document_id="doc-1", document_version_id="version-1",
        document_title="Control policy", original_filename="policy.md", version_no=1,
        section_id="section-1", section_ordinal=0, heading_path=("Controls",),
        section_title="Control", text=text, text_sha256="c" * 64, excerpt=text,
        anchor_id="aaaaaaaaaaaa", citation_id=citation, category="Security", topics=("access-control",),
        market_flags=(), persona_affinity={}, injection_flags=(), section_signature="d" * 64,
        document_manifest_sha256="a" * 64, finalization_target_digest="cft1:" + "b" * 64,
        anchor_algo_version="heading-path-v1", retrieval_score=10.0, retrieval_rank=1,
        matched_terms=("control",),
    )
    return TenantCorpusProvider(
        company_id="company-1", company_name="Example", user_id="user-1",
        documents=[{"id": "doc-1", "title": "Control policy", "short": "Control policy", "type": "Document", "category": "Security", "extent": "1 section", "lastUpdated": "", "format": "text", "citationPrefix": "FIX", "citationIds": [citation], "usedByPersonas": [], "topics": ["access-control"]}],
        sections=[{"documentId": "doc-1", "versionId": "version-1", "source": "Control policy", "sectionTitle": "Control", "headingPath": ["Controls"], "ordinal": 0, "text": text, "tokenSet": normalize_text(text).split(), "excerpt": text, "category": "Security", "topics": ["access-control"], "citationId": citation, "anchorId": "aaaaaaaaaaaa", "retrievalScore": 10.0, "retrievalRank": 1}],
        source_versions=(source,), evidence=(evidence,), snapshot_digest="tcs1:" + "e" * 64,
        config=TenantRetrievalConfig(50, 500, 40, 60000, 10, 1200),
    )


def provider_for_rows(rows: list[tuple[str, str, str]]) -> TenantCorpusProvider:
    """Build frozen evidence rows as (document id, 12-char anchor, text)."""
    base = provider_for(rows[0][2], f"FIX-{rows[0][1]}")
    base_documents, base_sections = base.load([])
    documents: dict[str, dict] = {}
    sources: dict[str, SourceVersionSnapshot] = {}
    evidence: list[RetrievedEvidence] = []
    sections: list[dict] = []
    for index, (document_id, anchor, text) in enumerate(rows):
        version_id = f"version-{document_id}"
        citation = f"FIX-{anchor}"
        documents.setdefault(document_id, {
            **base_documents[0],
            "id": document_id,
            "title": f"Policy {document_id}",
            "citationIds": [],
        })["citationIds"].append(citation)
        sources.setdefault(document_id, replace(
            base.source_versions[0],
            document_id=document_id,
            document_version_id=version_id,
            document_title=f"Policy {document_id}",
            position=len(sources),
        ))
        evidence.append(replace(
            base.evidence[0],
            document_id=document_id,
            document_version_id=version_id,
            document_title=f"Policy {document_id}",
            section_id=f"section-{index}",
            section_ordinal=index,
            text=text,
            excerpt=text,
            anchor_id=anchor,
            citation_id=citation,
            retrieval_rank=index + 1,
        ))
        sections.append({
            **base_sections[0],
            "documentId": document_id,
            "versionId": version_id,
            "source": f"Policy {document_id}",
            "ordinal": index,
            "text": text,
            "tokenSet": normalize_text(text).split(),
            "excerpt": text,
            "citationId": citation,
            "anchorId": anchor,
            "retrievalRank": index + 1,
        })
    return TenantCorpusProvider(
        company_id=base.company_id,
        company_name=base.company_name,
        user_id=base.user_id,
        documents=list(documents.values()),
        sections=sections,
        source_versions=tuple(sources.values()),
        evidence=tuple(evidence),
        snapshot_digest="tcs1:" + "f" * 64,
        config=base.config,
    )
def fixture_cases():
    raw = json.loads((MODULE_DIR / "claim-fixtures.json").read_text(encoding="utf-8"))
    for pattern in raw["patterns"]:
        for case in pattern["cases"]:
            yield pytest.param(pattern["claimSpecId"], case, id=f"{pattern['claimSpecId'].split('.')[-1]}-{case['id']}")


@pytest.mark.parametrize("claim_spec_id,case", list(fixture_cases()))
def test_claim_fixture_pack(claim_spec_id, case):
    result = run_claim_engine(provider_for(case["text"]))
    item = next(value for value in result.evaluated if value.candidate.claim_spec_id == claim_spec_id and value.candidate.candidate_source == "deterministic_pattern")
    assert item.decision.decision == case["expectedDecision"]
    assert case["expectedReason"] in item.decision.reason_codes
    assert bool(item.decision.accepted_binding_ids) is case["expectedBinding"]
    if case["expectedBinding"]:
        assert item.decision.accepted_binding_ids == ("FIX-aaaaaaaaaaaa",)


def test_fixture_evaluation_metrics_and_version_comparison():
    rows = []
    fixture = json.loads((MODULE_DIR / "claim-fixtures.json").read_text(encoding="utf-8"))
    for pattern in fixture["patterns"]:
        for case in pattern["cases"]:
            result = run_claim_engine(provider_for(case["text"]))
            item = next(
                value for value in result.evaluated
                if value.candidate.claim_spec_id == pattern["claimSpecId"]
            )
            rows.append({
                "expectedDecision": case["expectedDecision"],
                "actualDecision": item.decision.decision,
                "acceptedBindingIds": item.decision.accepted_binding_ids,
                "allowedBindingIds": ("FIX-aaaaaaaaaaaa",),
                "candidateSource": item.candidate.candidate_source,
            })
    metrics = claim_fixture_metrics(rows)
    assert metrics["fixtureCount"] == 35
    assert metrics["deterministicClaimPrecision"] == 1.0
    assert metrics["claimRecall"] == 1.0
    assert metrics["falsePositiveRate"] == 0.0
    assert metrics["insufficientEvidenceAccuracy"] == 1.0
    assert metrics["citationValidity"] == 1.0
    assert metrics["acceptedClaimBindingCompleteness"] == 1.0
    assert metrics["statisticalQualityClaimed"] is False
    comparison = compare_pattern_versions("1.0.0", metrics, "1.0.1", metrics)
    assert set(comparison["deltas"].values()) == {0.0}


def _temp_release(tmp_path: Path, monkeypatch, mutate):
    import app.claims.patterns as patterns

    raw = json.loads((MODULE_DIR / "claim-patterns.json").read_text(encoding="utf-8"))
    mutate(raw)
    directory = tmp_path / "compliance" / "claim-patterns" / "1.0.0"
    directory.mkdir(parents=True)
    (directory / "claim-patterns.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(patterns, "_MODULE_ROOT", tmp_path)
    return _load_release("compliance", "1.0.0")


def test_pattern_release_digest_is_deterministic():
    one = load_active_claim_patterns()
    two = _load_release("compliance", "1.0.0")
    assert one.release_digest == two.release_digest
    assert [spec.pattern_digest for spec in one.specs] == [spec.pattern_digest for spec in two.specs]


@pytest.mark.parametrize("mutation,match", [
    (lambda raw: raw["patterns"][0]["matcher"].update({"primitive": "eval_python"}), "unknown primitive"),
    (lambda raw: raw["patterns"].append(copy.deepcopy(raw["patterns"][0])), "duplicate"),
    (lambda raw: raw["patterns"][0]["output"].update({"statement": "eval(tenant_text)"}), "executable"),
    (lambda raw: raw["patterns"][0].update({"networkRef": "https://example.test"}), "unknown fields"),
    (lambda raw: raw["gatePolicies"][0].update({"acceptThreshold": 1.2}), "between"),
])
def test_malformed_pattern_releases_fail_closed(tmp_path, monkeypatch, mutation, match):
    with pytest.raises(PatternValidationError, match=match):
        _temp_release(tmp_path, monkeypatch, mutation)


def test_matcher_primitives_numeric_duration_proximity_classification_and_unicode():
    evidence = (EvidenceContext(
        "CIT-1", "CIT-1", "d", "v", "a",
        "Ａｄｍｉｎ access must be reviewed within 24 hours and value 99 percent.",
        "Privileged Access", "Security", ("access-control",),
    ),)
    assert evaluate_matcher({"primitive": "token_all", "terms": ["admin", "access"]}, evidence).matched
    assert evaluate_matcher({"primitive": "proximity", "left": ["reviewed"], "right": ["24"], "maxTokens": 3}, evidence).matched
    assert evaluate_matcher({"primitive": "duration_deadline", "maxHours": 24, "terms": ["reviewed"]}, evidence).values == (24.0,)
    assert evaluate_matcher({"primitive": "numeric_value", "min": 99, "max": 99, "units": ["percent"]}, evidence).values == (99.0,)
    assert evaluate_matcher({"primitive": "classification_match", "categories": ["Security"], "topics": ["access-control"], "match": "all"}, evidence).matched
    assert evaluate_matcher({"primitive": "heading_match", "terms": ["privileged", "access"], "mode": "all"}, evidence).matched


def test_combinators_and_evidence_count_are_stable():
    evidence = tuple(EvidenceContext(f"C-{i}", f"C-{i}", f"d-{i}", "v", f"a-{i}", "Backups must be tested.", "Backup", None, ()) for i in (2, 1))
    node = {"primitive": "evidence_count", "min": 2, "matcher": {"primitive": "token_all", "terms": ["backups", "tested"]}}
    observed = evaluate_matcher(node, evidence)
    assert observed.matched
    assert observed.binding_ids == ("C-1", "C-2")
    assert evaluate_matcher({"primitive": "not", "child": {"primitive": "token_any", "terms": ["never"]}}, evidence).matched
    assert evaluate_matcher({"primitive": "any_of", "children": [{"primitive": "token_any", "terms": ["missing"]}, {"primitive": "token_any", "terms": ["tested"]}]}, evidence).matched


def test_hash_seed_independence_for_claim_decisions(tmp_path):
    script = """
from tests.test_claim_engine import provider_for
from app.claims.engine import run_claim_engine
import json
r=run_claim_engine(provider_for('Administrative access must use MFA.'))
print(json.dumps([(x.candidate.claim_spec_id,x.decision.decision,x.decision.support_score,x.decision.accepted_binding_ids) for x in r.evaluated],sort_keys=True))
"""
    outputs = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outputs.append(subprocess.check_output([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1], env=env, text=True))
    assert outputs[0] == outputs[1]


def test_gate_rejects_foreign_binding():
    release = load_active_claim_patterns()
    spec = release.specs[0]
    result = run_claim_engine(provider_for("Administrative access must use MFA."), release=release)
    base = next(item for item in result.evaluated if item.spec == spec)
    candidate = ClaimCandidate(
        spec_ref=f"{spec.id}@{spec.version}", candidate_id="f" * 64,
        claim_spec_id=spec.id, pattern_version=spec.version,
        proposed_statement="proposal", source_snapshot_id="s", source_snapshot_digest="s",
        proposed_binding_ids=("FOREIGN-1",),
    )
    decision = decide_claim(candidate, spec, release.policies[spec.gate_policy_id], base.requirement_observations, allowed_binding_ids={"FIX-aaaaaaaaaaaa"}, binding_documents={"FIX-aaaaaaaaaaaa": "doc"})
    assert decision.decision == "rejected"
    assert decision.reason_codes == (REASON_FOREIGN_EVIDENCE,)


def test_llm_proposals_use_same_gate_and_hallucinated_citations_are_rejected():
    proposals = [
        {"claimSpecId": "compliance.administrative-access-mfa", "statement": "MFA protects administrator access.", "evidenceCodes": ["FIX-aaaaaaaaaaaa"], "model": "m", "promptVersion": "p"},
        {"claimSpecId": "compliance.administrative-access-mfa", "statement": "Invented.", "evidenceCodes": ["HALLUCINATED-1"], "model": "m", "promptVersion": "p"},
    ]
    result = run_claim_engine(provider_for("Administrative access must use MFA."), llm_proposals=proposals)
    llm = [item for item in result.evaluated if item.candidate.candidate_source == "llm_proposal"]
    assert [item.decision.decision for item in llm] == ["accepted", "rejected"]
    assert llm[1].decision.reason_codes == (REASON_FOREIGN_EVIDENCE,)
    risks, included = accepted_claim_risks(result)
    assert any(risk["description"] == "MFA protects administrator access." for risk in risks)
    assert llm[0].candidate.candidate_id in included
    assert llm[1].candidate.candidate_id not in included


def test_llm_selective_citation_cannot_hide_frozen_mfa_conflict(monkeypatch):
    provider = provider_for_rows([
        ("doc-a", "aaaaaaaaaaaa", "Administrative access must use MFA."),
        ("doc-b", "bbbbbbbbbbbb", "Administrative access is not required to use MFA."),
    ])
    proposal = {
        "claimSpecId": "compliance.administrative-access-mfa",
        "statement": "MFA protects administrator access.",
        "evidenceCodes": ["FIX-aaaaaaaaaaaa"],
    }
    result = run_claim_engine(provider, llm_proposals=[proposal])
    llm = next(item for item in result.evaluated if item.candidate.candidate_source == "llm_proposal")
    assert llm.decision.decision == "rejected"
    assert "CONTRADICTING_EVIDENCE" in llm.decision.reason_codes
    assert llm.decision.conflicting_evidence == ("FIX-bbbbbbbbbbbb",)
    conflict_audits = [
        observation for observation in llm.candidate.matcher_observations
        if observation["purpose"] == "conflict"
    ]
    assert any("FIX-bbbbbbbbbbbb" in row["bindingIds"] for row in conflict_audits)

    settings = get_settings()
    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", True)
    report, telemetry = run_pipeline_ex(
        "EMEA", "Compliance Officer", "", ["doc-a", "doc-b"],
        section_provider=provider, intensity_override="off", use_cache=False,
    )
    assert report["workflowSteps"] == []
    assert report["risks"] == []
    assert report["suggestedActions"] == []
    assert "No accepted claim" in report["topFinding"]
    assert "did not support any accepted claim" in report["summary"]
    analytical = json.dumps({key: report[key] for key in (
        "workflowSteps", "risks", "suggestedActions", "summary", "topFinding"
    )})
    assert "MFA protects administrator access" not in analytical
    assert telemetry["_includedClaimCandidateIds"] == []


def test_gate_uses_only_matcher_attributed_support_bindings():
    provider = provider_for_rows([
        ("doc-a", "aaaaaaaaaaaa", "Administrative access must use MFA."),
        ("doc-b", "bbbbbbbbbbbb", "The cafeteria closes at five."),
    ])
    base = {
        "claimSpecId": "compliance.administrative-access-mfa",
        "statement": "MFA protects administrator access.",
    }
    relevant = run_claim_engine(provider, llm_proposals=[{
        **base, "evidenceCodes": ["FIX-aaaaaaaaaaaa"]
    }]).evaluated[-1]
    padded = run_claim_engine(provider, llm_proposals=[{
        **base, "evidenceCodes": ["FIX-aaaaaaaaaaaa", "FIX-bbbbbbbbbbbb", "FIX-aaaaaaaaaaaa"]
    }]).evaluated[-1]
    assert relevant.decision.decision == padded.decision.decision == "accepted"
    assert relevant.decision.support_score == padded.decision.support_score
    assert relevant.decision.accepted_binding_ids == padded.decision.accepted_binding_ids == (
        "FIX-aaaaaaaaaaaa",
    )
    assert padded.decision.deterministic_features["bindingCount"] == 1.0
    unrelated_only = run_claim_engine(provider, llm_proposals=[{
        **base, "evidenceCodes": ["FIX-bbbbbbbbbbbb"]
    }]).evaluated[-1]
    assert unrelated_only.decision.decision == "insufficient_evidence"
    assert unrelated_only.decision.accepted_binding_ids == ()


def test_support_binding_and_source_diversity_deduplicate_canonically():
    same_document = provider_for_rows([
        ("doc-a", "aaaaaaaaaaaa", "Administrative access must use MFA."),
        ("doc-a", "bbbbbbbbbbbb", "Administrative accounts shall require MFA."),
    ])
    different_documents = provider_for_rows([
        ("doc-a", "aaaaaaaaaaaa", "Administrative access must use MFA."),
        ("doc-b", "bbbbbbbbbbbb", "Administrative accounts shall require MFA."),
    ])
    proposal = {
        "claimSpecId": "compliance.administrative-access-mfa",
        "statement": "MFA is required.",
        "evidenceCodes": ["FIX-aaaaaaaaaaaa", "FIX-bbbbbbbbbbbb", "FIX-bbbbbbbbbbbb"],
    }
    same = run_claim_engine(same_document, llm_proposals=[proposal]).evaluated[-1].decision
    different = run_claim_engine(different_documents, llm_proposals=[proposal]).evaluated[-1].decision
    assert same.accepted_binding_ids == different.accepted_binding_ids == (
        "FIX-aaaaaaaaaaaa", "FIX-bbbbbbbbbbbb"
    )
    assert same.deterministic_features["bindingCount"] == 2.0
    assert same.deterministic_features["sourceCount"] == 1.0
    assert different.deterministic_features["sourceCount"] == 2.0


def test_full_mode_exception_restores_complete_claim_baseline(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", True)
    monkeypatch.setattr(settings, "evidentia_use_llm", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    provider = provider_for("Administrative access must use MFA.")
    baseline, baseline_tel = run_pipeline_ex(
        "EMEA", "Compliance Officer", "", ["doc-1"], section_provider=provider,
        intensity_override="off", use_cache=False,
    )

    monkeypatch.setattr(orchestrator_module, "_llm_persona_workflow", lambda *args, **kwargs: (
        LLMCallResult({}, True, 10),
        {**copy.deepcopy(args[4]), "description": "Partial LLM persona"},
        [{**copy.deepcopy(args[5][0]), "description": "Partial LLM workflow"}],
    ))
    monkeypatch.setattr(orchestrator_module, "_llm_claim_proposals", lambda *args, **kwargs: (
        LLMCallResult({}, True, 10),
        [{
            "claimSpecId": "compliance.administrative-access-mfa",
            "statement": "Partial LLM risk wording.",
            "evidenceCodes": ["FIX-aaaaaaaaaaaa"],
        }],
    ))
    monkeypatch.setattr(orchestrator_module, "reconcile_and_gate", lambda **kwargs: {
        **kwargs["cand"], "telemetry": {**orchestrator_module.default_structural_telemetry()}
    })
    original_binder = orchestrator_module.citation_binder

    def fail_after_assignment(sections, workflow, risks):
        if any(risk.get("description") == "Partial LLM risk wording." for risk in risks):
            raise RuntimeError("post-assignment failure")
        return original_binder(sections, workflow, risks)

    monkeypatch.setattr(orchestrator_module, "citation_binder", fail_after_assignment)
    final, telemetry = run_pipeline_ex(
        "EMEA", "Compliance Officer", "", ["doc-1"], section_provider=provider,
        intensity_override="full", use_cache=False,
    )
    for field in (
        "personaBrief", "workflowSteps", "risks", "suggestedActions", "summary", "topFinding"
    ):
        assert final[field] == baseline[field]
    assert final["generationMode"] == "deterministic"
    assert final["llmProvider"] == "none"
    assert telemetry["fullModeAnalyticalFallback"] is True
    assert telemetry["_includedClaimCandidateIds"] == baseline_tel["_includedClaimCandidateIds"]
    assert all(
        item.candidate.candidate_source == "deterministic_pattern"
        for item in telemetry["_claimRunResult"].evaluated
    )


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_released_m3_module_and_all_goldens_are_exact_head_bytes():
    backend = Path(__file__).resolve().parents[1]
    module = backend / "app" / "modules" / "compliance" / "1.0.0"
    goldens = backend / "tests" / "golden" / "expected"
    assert sorted(item.name for item in module.iterdir()) == [
        "module.json", "signatures.json", "taxonomy.json"
    ]
    assert _tree_digest(module) == "c2f661654254467fc308b7f0781756fceba2dd6ec8116a28133426f2469da7e9"
    assert len(list(goldens.glob("*.json"))) == 17
    assert _tree_digest(goldens) == "83820437125afd2c477f61b39b9b74fa6bc8525d4761160174edd8dd62afb252"


def test_claim_pack_is_independent_reproducible_and_explicitly_selected(tmp_path, monkeypatch):
    module = get_active_module()
    finalization = build_finalization_target("markdown", module).digest
    release = load_active_claim_patterns()
    assert release.claim_pack_id == "compliance.claim-patterns"
    assert release.release_version == "1.0.0"
    assert module.digest == "c808fa81ce45d69ea05a4009166d037f9e9333873fedcc360b32bce3ffa10823"

    changed = _temp_release(
        tmp_path,
        monkeypatch,
        lambda raw: raw["patterns"][0]["output"].update({"statement": "Changed statement"}),
    )
    assert changed.release_digest != release.release_digest
    assert changed.specs[0].pattern_digest != release.specs[0].pattern_digest
    assert get_active_module().digest == module.digest
    assert build_finalization_target("markdown", get_active_module()).digest == finalization

    import app.claims.patterns as patterns
    raw = copy.deepcopy(release.raw)
    raw["releaseVersion"] = "1.0.1"
    directory = tmp_path / "compliance" / "claim-patterns" / "1.0.1"
    directory.mkdir(parents=True)
    (directory / "claim-patterns.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(patterns, "_MODULE_ROOT", tmp_path)
    selected = _load_release("compliance", "1.0.1")
    assert selected.release_version == "1.0.1"


@pytest.mark.parametrize("mutation,match", [
    (
        lambda raw: raw["patterns"][0].update({
            "matcher": {"primitive": "evidence_count", "min": 1, "matcher": {
                "primitive": "evidence_count", "min": 1,
                "matcher": {"primitive": "token_any", "terms": ["mfa"]},
            }}
        }),
        "evidence_count nesting",
    ),
    (
        lambda raw: raw["patterns"][0].update({
            "matcher": {"primitive": "comparison", "feature": "source_count", "operator": "gte", "value": 1}
        }),
        "unknown primitive",
    ),
    (lambda raw: raw["provenance"].update({"fixturePack": "C:\\outside.json"}), "release-relative"),
    (lambda raw: raw["provenance"].update({"fixturePack": "../outside.json"}), "external files"),
])
def test_pattern_budget_comparison_and_path_references_fail_atomically(
    tmp_path, monkeypatch, mutation, match
):
    with pytest.raises(PatternValidationError, match=match):
        _temp_release(tmp_path, monkeypatch, mutation)


def test_flag_off_preserves_m4_and_flag_on_projects_only_accepted_claims(monkeypatch):
    settings = get_settings()
    provider = provider_for("Administrative access must use MFA. Emergency access is not reviewed within 24 hours.")
    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", False)
    off, off_tel = run_pipeline_ex("EMEA", "Compliance Officer", "", ["doc-1"], section_provider=provider, intensity_override="off", use_cache=False)
    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", True)
    on, on_tel = run_pipeline_ex("EMEA", "Compliance Officer", "", ["doc-1"], section_provider=provider, intensity_override="off", use_cache=False)
    assert set(on) == set(off)
    assert len(on) == 20
    assert on_tel["claimEngine"]["enabled"] is True
    assert any(risk["title"] == "Administrative MFA requirement requires implementation assurance" for risk in on["risks"])
    assert all("Emergency-access" not in risk["title"] for risk in on["risks"])
    assert all(risk["evidenceCode"] == "FIX-aaaaaaaaaaaa" for risk in on["risks"])
