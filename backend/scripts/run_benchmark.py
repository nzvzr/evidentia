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
from app.eval.export import write_csv, write_json  # noqa: E402
from app.eval.runner import DEFAULT_MODES, run_benchmark, summarize  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Evidentia LLM benchmark.")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES),
                        help="comma-separated: deterministic,summary,full,auto")
    parser.add_argument("--out-dir", default="benchmark_results")
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

    print(f"\nWrote {stem}.json and {stem}.csv\n")
    header = f"{'mode':<14}{'avgScore':>9}{'schemaOK':>9}{'citAcc':>8}{'halluc':>8}{'calls':>7}{'tokens':>9}{'costUSD':>10}{'latMs':>9}"
    print(header)
    print("-" * len(header))
    for mode, s in summary.items():
        print(
            f"{mode:<14}{s['avgQualityScore']:>9}{s['schemaValidRate']:>9}"
            f"{s['avgCitationAccuracy']:>8}{s['avgHallucinationWarnings']:>8}"
            f"{s['totalLlmCalls']:>7}{s['totalTokens']:>9}{s['totalEstimatedCostUsd']:>10}{s['avgLatencyMs']:>9}"
        )


if __name__ == "__main__":
    main()
