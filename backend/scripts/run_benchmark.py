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

from app.eval.dataset import BENCHMARK_VERSION, scenario_count  # noqa: E402
from app.eval.export import write_audit_csv, write_csv, write_json  # noqa: E402
from app.eval.runner import DEFAULT_MODES, run_benchmark, summarize  # noqa: E402


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Evidentia LLM benchmark.")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES),
                        help="comma-separated: deterministic,summary,full,auto")
    parser.add_argument("--out-dir", default="benchmark_results")
    parser.add_argument("--print-repairs", action="store_true",
                        help="print every repaired citation, matched terms, score, and ground-truth match")
    args = parser.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    print(f"Evidentia benchmark {BENCHMARK_VERSION} · {scenario_count()} scenarios × modes={modes}")

    results = run_benchmark(modes=modes)
    summary = summarize(results)

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = os.path.join(args.out_dir, f"benchmark_{BENCHMARK_VERSION}_{ts}")
    write_json(f"{stem}.json", results, summary)
    write_csv(f"{stem}.csv", results)
    write_audit_csv(f"{stem}.audit.csv", results)

    if args.print_repairs:
        _print_repairs(results)

    print(f"\nWrote {stem}.json, {stem}.csv and {stem}.audit.csv\n")
    header = (
        f"{'mode':<12}{'overall':>8}{'narr':>7}{'ungrB':>6}{'ungrA':>6}"
        f"{'repl':>5}{'insuf':>6}{'avgRlv':>7}{'exp%':>6}{'calls':>6}{'cost$':>9}"
    )
    print(header)
    print("-" * len(header))
    for mode, s in summary.items():
        print(
            f"{mode:<12}{s['avgOverallQualityScore']:>8}{s['avgNarrativeUtilityScore']:>7}"
            f"{s['ungroundedBeforeRepair']:>6}{s['ungroundedAfterRepair']:>6}"
            f"{s['repairReplaced']:>5}{s['repairInsufficient']:>6}"
            f"{s['averageRepairRelevanceScore']:>7}{s['expectedEvidenceMatchRate']:>6}"
            f"{s['totalLlmCalls']:>6}{s['totalEstimatedCostUsd']:>9}"
        )
    print("\nungrB/ungrA = ungrounded evidence before/after repair · repl/insuf = repaired/insufficient · "
          "avgRlv = avg repair relevance · exp% = expected-evidence match rate")


if __name__ == "__main__":
    main()
