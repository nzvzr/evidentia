#!/usr/bin/env python
"""Run the Evidentia LLM benchmark and export JSON + CSV.

Examples:
    python scripts/run_benchmark.py
    python scripts/run_benchmark.py --modes deterministic,summary,full,auto
    python scripts/run_benchmark.py --out-dir benchmark_results
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.eval.dataset import BENCHMARK_VERSION, SCENARIOS, scenario_count  # noqa: E402
from app.eval.export import (  # noqa: E402
    write_audit_csv,
    write_csv,
    write_generation_audit_csv,
    write_json,
)
from app.eval.runner import (  # noqa: E402
    DEFAULT_MODES,
    compare_modes,
    filter_scenarios,
    run_benchmark,
    summarize,
)


def _print_repairs(results) -> None:
    print("\n--- repaired citations ---")
    any_repairs = False
    for row in results:
        for a in row.get("repairAudit", []):
            any_repairs = True
            gt = "✓gt" if a.get("matchedExpected") else "·"
            terms = ", ".join(a.get("matchedTerms", [])) or "-"
            print(
                f"[{row['requestedMode']:<13}] {row['scenarioId']:<26} {a['itemType']:<8} "
                f"{a['originalEvidenceCode']:>7} → {a['replacementEvidenceCode']:<6} "
                f"score={a['relevanceScore']:<6} {gt:<4} terms=[{terms}] :: {a['itemTitle'][:60]}"
            )
    if not any_repairs:
        print("(no invalid evidence codes required repair)")


def _print_generation(results) -> None:
    print("\n--- dropped / transformed generated items ---")
    any_dropped = False
    for row in results:
        for a in row.get("generationAudit", []):
            any_dropped = True
            print(
                f"[{row['requestedMode']:<13}] {row['scenarioId']:<26} {a['itemType']:<8} "
                f"{a['finalDecision']:<13} score={a['supportScore']:<6} "
                f"reason={a['rejectionReason']:<28} :: {a['title'][:56]}"
            )
    if not any_dropped:
        print("(no risks or steps were dropped or converted to evidence gaps)")


def _print_compare(comp) -> None:
    if not comp:
        return
    print("\n--- cross-mode analysis ---")
    for pair in ("fullVsDeterministic", "fullVsSummary"):
        if pair in comp:
            w = comp[pair]
            print(f"{pair:<20} win/tie/loss = {w['win']}/{w['tie']}/{w['loss']}")
    if comp.get("fullIncrementalGainVsSummary") is not None:
        print(f"full incremental gain vs summary (overall): {comp['fullIncrementalGainVsSummary']}")
    if "fullStructuralRegressionsBeforeGate" in comp:
        print(f"full structural regressions before/after gate: "
              f"{comp['fullStructuralRegressionsBeforeGate']} -> {comp['fullStructuralRegressionsAfterGate']}")
        print(f"full accepted structural components/items: "
              f"{comp['fullAcceptedStructuralComponents']}/{comp['fullAcceptedAnalyticalItems']}")
        print(f"full total cost ${comp['fullTotalCostUsd']} · "
              f"cost/accepted-component ${comp.get('costPerAcceptedComponentUsd')} · "
              f"cost/accepted-item ${comp.get('costPerAcceptedItemUsd')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Evidentia LLM benchmark.")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES),
                        help="comma-separated: deterministic,summary,full,auto")
    parser.add_argument("--out-dir", default="benchmark_results")
    parser.add_argument("--runs", type=int, default=1, help="repeat each scenario N times")
    parser.add_argument("--scenario", default="", help="comma-separated scenario ids to include")
    parser.add_argument("--category", default="", help="comma-separated categories to include")
    parser.add_argument("--print-repairs", action="store_true",
                        help="print every repaired citation, matched terms, score, and ground-truth match")
    parser.add_argument("--print-generation", action="store_true",
                        help="print every dropped or evidence-gap risk/step with its support score and reason")
    args = parser.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    scenario_ids = [s.strip() for s in args.scenario.split(",") if s.strip()] or None
    categories = [c.strip() for c in args.category.split(",") if c.strip()] or None
    scenarios = filter_scenarios(SCENARIOS, scenario_ids, categories)
    print(f"Evidentia benchmark {BENCHMARK_VERSION} · {len(scenarios)}/{scenario_count()} scenarios "
          f"× modes={modes} × runs={args.runs}")

    results = run_benchmark(modes=modes, scenarios=scenarios, runs=args.runs)
    summary = summarize(results)
    comparison = compare_modes(results)

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = os.path.join(args.out_dir, f"benchmark_{BENCHMARK_VERSION}_{ts}")
    write_json(f"{stem}.json", results, summary)
    write_csv(f"{stem}.csv", results)
    write_audit_csv(f"{stem}.audit.csv", results)
    write_generation_audit_csv(f"{stem}.gen-audit.csv", results)

    if args.print_repairs:
        _print_repairs(results)
    if args.print_generation:
        _print_generation(results)

    print(f"\nWrote {stem}.json, {stem}.csv, {stem}.audit.csv and {stem}.gen-audit.csv\n")
    header = (
        f"{'mode':<12}{'overall':>8}{'±std':>7}{'narr':>7}{'struct':>7}{'sReg':>6}"
        f"{'exact':>7}{'famly':>7}{'docmt':>7}{'cncpt':>7}{'lat(ms)':>9}{'cost$':>9}"
    )
    print(header)
    print("-" * len(header))
    for mode, s in summary.items():
        def _f(v):
            return "-" if v is None else f"{v}"
        print(
            f"{mode:<12}{s['avgOverallQualityScore']:>8}{s['overallQualityStd']:>7}"
            f"{s['avgNarrativeUtilityScore']:>7}{s['avgFinalStructuralScore']:>7}"
            f"{s['structuralRegressionsAfterGate']:>6}"
            f"{_f(s['avgExpectedCitationExactMatchRate']):>7}{_f(s['avgExpectedCitationFamilyMatchRate']):>7}"
            f"{_f(s['avgExpectedSourceDocumentMatchRate']):>7}{_f(s['avgExpectedRiskConceptRecall']):>7}"
            f"{s['avgLatencyMs']:>9}{s['totalEstimatedCostUsd']:>9}"
        )
    print("\nstruct = final structural score · sReg = structural regressions after gate · "
          "exact/famly/docmt/cncpt = expected citation exact / family / document / risk-concept match")

    _print_compare(comparison)


if __name__ == "__main__":
    main()
