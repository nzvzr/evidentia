#!/usr/bin/env python
"""Offline router calibration for Evidentia (Phases 1 & 2).

Determines whether auto-routing has enough theoretical value to justify its
complexity BEFORE tuning thresholds:

  Phase 1  oracle analysis   — best-possible per-scenario mode, gain vs summary,
                               cost/latency, mode distribution, Pareto frontier.
  Phase 2  policy comparison — always-{det,summary,full}, the previous auto router,
                               the proposed calibrated router, and the oracle upper
                               bound, under hard cost/latency/regression constraints,
                               with leave-one-category-out validation and a small
                               interpretable threshold search.

Usage:
    python scripts/calibrate_router.py --input benchmark_results/benchmark_v1_*.json
    python scripts/calibrate_router.py --run --modes deterministic,summary,full
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from statistics import mean
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.mode_router import RoutingSignals, route_intensity  # noqa: E402

MODES = ["deterministic", "summary", "full"]
# tie preference: cheaper/faster first
PREF_ORDER = ["deterministic", "summary", "full"]
INTENSITY = {"deterministic": "off", "summary": "summary", "full": "full"}


# --------------------------------------------------------------------------- #
# data loading
# --------------------------------------------------------------------------- #

def _load_results(args) -> List[Dict[str, Any]]:
    if args.input:
        path = args.input
    elif args.run:
        from app.eval.runner import run_benchmark
        print(f"Running benchmark modes={MODES} runs={args.runs} ...")
        return run_benchmark(modes=MODES, runs=args.runs)
    else:
        matches = sorted(glob.glob(os.path.join("benchmark_results", "benchmark_*.json")))
        if not matches:
            sys.exit("No benchmark json found; pass --input or --run.")
        path = matches[-1]
    print(f"Loading {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["results"]


def _aggregate(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """scenarioId -> {mode -> {overall, cost, latency}, features, category}."""
    by_scenario: Dict[str, Dict[str, Any]] = {}
    for r in results:
        sid = r["scenarioId"]
        s = by_scenario.setdefault(sid, {"category": r["category"], "modes": {}, "features": None})
        m = s["modes"].setdefault(r["requestedMode"], {"overall": [], "cost": [], "latency": []})
        m["overall"].append(r["overallQualityScore"])
        m["cost"].append(r["estimatedCostUsd"])
        m["latency"].append(r["latencyMs"])
        if r["requestedMode"] == "deterministic":
            s["features"] = _features(r)
    for s in by_scenario.values():
        for m in s["modes"].values():
            m["overall"] = round(mean(m["overall"]), 3)
            m["cost"] = mean(m["cost"])
            m["latency"] = mean(m["latency"])
    return by_scenario


def _features(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "deterministic_structural_score": row.get("deterministicStructuralScoreBaseline", 0.0),
        "deterministic_narrative_score": row.get("deterministicNarrativeScoreBaseline", 0.0),
        "document_complexity": row.get("documentComplexity", 0),
        "contradictions": row.get("contradictions", 0),
        "persona_complexity": row.get("personaComplexity", 0),
        "deterministic_confidence": row.get("deterministicConfidence", 0),
        "citation_coverage": row.get("citationCoverage", 0.0),
        "grounded_risks_kept": row.get("groundedRisksKept", 0),
        "grounded_workflow_steps_kept": row.get("groundedWorkflowStepsKept", 0),
        "unsupported_risks_dropped": row.get("unsupportedRisksDropped", 0),
        "insufficient_evidence_items": row.get("insufficientEvidenceItemsFinal", 0),
        "source_document_mismatch": row.get("sourceDocumentMismatchCount", 0),
        "evidence_support_score_avg": row.get("evidenceSupportScoreAvg", 0.0),
        "evidence_support_score_min": row.get("evidenceSupportScoreMin", 0.0),
    }


# --------------------------------------------------------------------------- #
# policies (features -> mode)
# --------------------------------------------------------------------------- #

def proposed_policy(full_gain_threshold: float) -> Callable[[Dict[str, Any]], str]:
    def policy(f: Dict[str, Any]) -> str:
        d = route_intensity(RoutingSignals(**f), full_gain_threshold=full_gain_threshold)
        return INTENSITY_INV[d.mode]
    return policy


INTENSITY_INV = {"off": "deterministic", "summary": "summary", "full": "full"}


def previous_auto_policy(f: Dict[str, Any]) -> str:
    """The aggressive pre-calibration router (for before/after comparison)."""
    if f["document_complexity"] <= 1:
        return "summary"
    if (f["contradictions"] >= 1 or f["persona_complexity"] >= 1
            or f["document_complexity"] >= 6 or f["deterministic_confidence"] < 84):
        return "full"
    if (f["deterministic_confidence"] >= 92 and f["citation_coverage"] >= 90
            and f["contradictions"] == 0 and f["persona_complexity"] == 0):
        return "deterministic"
    return "summary"


# --------------------------------------------------------------------------- #
# oracle + evaluation
# --------------------------------------------------------------------------- #

def oracle_mode(scores: Dict[str, float], epsilon: float) -> str:
    best = max(scores.values())
    cands = [m for m in MODES if best - scores[m] <= epsilon]
    for m in PREF_ORDER:
        if m in cands:
            return m
    return "summary"


def evaluate(policy: Callable[[Dict[str, Any]], str], data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    picks = {sid: policy(s["features"]) for sid, s in data.items()}
    overalls = [data[sid]["modes"][m]["overall"] for sid, m in picks.items()]
    costs = [data[sid]["modes"][m]["cost"] for sid, m in picks.items()]
    lats = [data[sid]["modes"][m]["latency"] for sid, m in picks.items()]
    regressions = [data[sid]["modes"]["summary"]["overall"] - data[sid]["modes"][m]["overall"]
                   for sid, m in picks.items()]
    dist = {m: sum(1 for v in picks.values() if v == m) for m in MODES}
    return {
        "avgOverall": round(mean(overalls), 3),
        "totalCost": round(sum(costs), 6),
        "avgLatencyMs": round(mean(lats), 1),
        "worstRegressionVsSummary": round(max(regressions), 3),
        "modeDistribution": dist,
        "picks": picks,
    }


def constraints_ok(ev: Dict[str, Any], summary_ev: Dict[str, Any]) -> Dict[str, bool]:
    return {
        "noAvgRegression": ev["avgOverall"] >= summary_ev["avgOverall"] - 0.05,
        "noScenarioRegressionOver0.5": ev["worstRegressionVsSummary"] <= 0.5,
        "costWithin125pct": ev["totalCost"] <= summary_ev["totalCost"] * 1.25 + 1e-9,
        "latencyWithin150pct": ev["avgLatencyMs"] <= summary_ev["avgLatencyMs"] * 1.5 + 1e-9,
    }


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

def _pareto(points: Dict[str, Dict[str, float]]) -> List[str]:
    """Pareto-optimal modes: maximize quality, minimize cost & latency."""
    frontier = []
    for m, p in points.items():
        dominated = False
        for m2, q in points.items():
            if m2 == m:
                continue
            if (q["quality"] >= p["quality"] and q["cost"] <= p["cost"] and q["latency"] <= p["latency"]
                    and (q["quality"] > p["quality"] or q["cost"] < p["cost"] or q["latency"] < p["latency"])):
                dominated = True
                break
        if not dominated:
            frontier.append(m)
    return frontier


def phase1_oracle(data: Dict[str, Dict[str, Any]], epsilon: float) -> Dict[str, Any]:
    summary_avg = mean(s["modes"]["summary"]["overall"] for s in data.values())
    oracle_picks = {sid: oracle_mode({m: s["modes"][m]["overall"] for m in MODES}, epsilon)
                    for sid, s in data.items()}
    oracle_overall = mean(data[sid]["modes"][m]["overall"] for sid, m in oracle_picks.items())
    oracle_cost = sum(data[sid]["modes"][m]["cost"] for sid, m in oracle_picks.items())
    oracle_lat = mean(data[sid]["modes"][m]["latency"] for sid, m in oracle_picks.items())
    dist = {m: sum(1 for v in oracle_picks.values() if v == m) for m in MODES}

    full_better = []
    gains_per_dollar, gains_per_sec = [], []
    for sid, s in data.items():
        g = s["modes"]["full"]["overall"] - s["modes"]["summary"]["overall"]
        if g > epsilon:
            full_better.append({"scenarioId": sid, "gain": round(g, 3)})
            dc = s["modes"]["full"]["cost"] - s["modes"]["summary"]["cost"]
            dl = (s["modes"]["full"]["latency"] - s["modes"]["summary"]["latency"]) / 1000.0
            if dc > 0:
                gains_per_dollar.append(g / dc)
            if dl > 0:
                gains_per_sec.append(g / dl)

    points = {m: {"quality": mean(s["modes"][m]["overall"] for s in data.values()),
                  "cost": sum(s["modes"][m]["cost"] for s in data.values()),
                  "latency": mean(s["modes"][m]["latency"] for s in data.values())} for m in MODES}

    return {
        "epsilon": epsilon,
        "oracleAvgOverall": round(oracle_overall, 3),
        "alwaysSummaryAvgOverall": round(summary_avg, 3),
        "oracleGainVsSummary": round(oracle_overall - summary_avg, 3),
        "oracleTotalCost": round(oracle_cost, 6),
        "oracleAvgLatencyMs": round(oracle_lat, 1),
        "oracleModeDistribution": dist,
        "scenariosWhereFullBeatsSummary": full_better,
        "fullGainPerExtraDollar": round(mean(gains_per_dollar), 3) if gains_per_dollar else None,
        "fullGainPerExtraSecond": round(mean(gains_per_sec), 3) if gains_per_sec else None,
        "aggregatePoints": {m: {k: round(v, 4) for k, v in p.items()} for m, p in points.items()},
        "paretoFrontier": _pareto(points),
    }


def phase2_policies(data: Dict[str, Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    named = {
        "always-deterministic": lambda f: "deterministic",
        "always-summary": lambda f: "summary",
        "always-full": lambda f: "full",
        "previous-auto": previous_auto_policy,
        "proposed-calibrated": proposed_policy(threshold),
    }
    summary_ev = evaluate(named["always-summary"], data)
    out = {}
    for name, pol in named.items():
        ev = evaluate(pol, data)
        ev["constraints"] = constraints_ok(ev, summary_ev)
        ev["constraintsAllPass"] = all(ev["constraints"].values())
        ev["beatsSummaryBy0.2"] = ev["avgOverall"] - summary_ev["avgOverall"] >= 0.2
        out[name] = ev
    return out


def phase2_threshold_search(data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Small interpretable search + leave-one-category-out validation."""
    grid = [0.0, 0.1, 0.2, 0.3, 0.45, 0.6, 0.75, 1.0]
    categories = sorted({s["category"] for s in data.values()})
    summary_ev = evaluate(lambda f: "summary", data)

    # full-data search
    full_search = []
    for t in grid:
        ev = evaluate(proposed_policy(t), data)
        ok = constraints_ok(ev, summary_ev)
        full_search.append({"threshold": t, "avgOverall": ev["avgOverall"],
                            "beatsSummaryBy0.2": ev["avgOverall"] - summary_ev["avgOverall"] >= 0.2,
                            "constraintsAllPass": all(ok.values()),
                            "modeDistribution": ev["modeDistribution"]})

    # leave-one-category-out: pick best feasible threshold on train, score on held-out
    loco = []
    for held in categories:
        train = {sid: s for sid, s in data.items() if s["category"] != held}
        test = {sid: s for sid, s in data.items() if s["category"] == held}
        train_summary = evaluate(lambda f: "summary", train)
        best_t, best_avg = None, -1.0
        for t in grid:
            ev = evaluate(proposed_policy(t), train)
            if all(constraints_ok(ev, train_summary).values()) and ev["avgOverall"] > best_avg:
                best_avg, best_t = ev["avgOverall"], t
        test_ev = evaluate(proposed_policy(best_t if best_t is not None else 0.2), test)
        test_summary = evaluate(lambda f: "summary", test)
        loco.append({
            "heldOutCategory": held, "chosenThreshold": best_t,
            "testAvgOverall": test_ev["avgOverall"],
            "testAlwaysSummary": test_summary["avgOverall"],
            "testGainVsSummary": round(test_ev["avgOverall"] - test_summary["avgOverall"], 3),
            "testModeDistribution": test_ev["modeDistribution"],
        })
    return {"gridSearch": full_search, "leaveOneCategoryOut": loco}


def main() -> None:
    p = argparse.ArgumentParser(description="Calibrate the Evidentia auto router.")
    p.add_argument("--input", default="", help="benchmark json (defaults to latest in benchmark_results)")
    p.add_argument("--run", action="store_true", help="run a fresh benchmark instead of loading json")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--epsilon", type=float, default=0.2, help="tie epsilon in overall points")
    p.add_argument("--full-gain-threshold", type=float, default=0.2)
    p.add_argument("--out", default="benchmark_results/router_calibration.json")
    args = p.parse_args()

    results = _load_results(args)
    data = _aggregate(results)
    print(f"Scenarios: {len(data)} · modes present: {sorted({m for s in data.values() for m in s['modes']})}\n")

    oracle = phase1_oracle(data, args.epsilon)
    policies = phase2_policies(data, args.full_gain_threshold)
    search = phase2_threshold_search(data)

    print("=== Phase 1 · Oracle (epsilon={}) ===".format(args.epsilon))
    print(f"oracle avg overall     : {oracle['oracleAvgOverall']}  "
          f"(always-summary {oracle['alwaysSummaryAvgOverall']}, gain {oracle['oracleGainVsSummary']})")
    print(f"oracle cost / latency  : ${oracle['oracleTotalCost']} / {oracle['oracleAvgLatencyMs']} ms")
    print(f"oracle mode distribution: {oracle['oracleModeDistribution']}")
    print(f"full beats summary in  : {len(oracle['scenariosWhereFullBeatsSummary'])} scenarios "
          f"{[s['scenarioId'] for s in oracle['scenariosWhereFullBeatsSummary']]}")
    print(f"full gain per $ / per s: {oracle['fullGainPerExtraDollar']} / {oracle['fullGainPerExtraSecond']}")
    print(f"Pareto frontier        : {oracle['paretoFrontier']}")
    for m, pt in oracle["aggregatePoints"].items():
        print(f"   {m:<14} quality {pt['quality']:<7} cost ${pt['cost']:<10} latency {pt['latency']} ms")

    print("\n=== Phase 2 · Policy comparison ===")
    print(f"{'policy':<22}{'avgOverall':>11}{'cost$':>10}{'lat(ms)':>9}{'worstReg':>9}{'ok':>4}{'>+0.2':>7}  dist")
    for name, ev in policies.items():
        print(f"{name:<22}{ev['avgOverall']:>11}{round(ev['totalCost'],5):>10}{ev['avgLatencyMs']:>9}"
              f"{ev['worstRegressionVsSummary']:>9}{str(ev['constraintsAllPass']):>4}{str(ev['beatsSummaryBy0.2']):>7}"
              f"  {ev['modeDistribution']}")

    print("\n=== Phase 2 · Threshold search (full data) ===")
    for g in search["gridSearch"]:
        print(f"  t={g['threshold']:<5} avgOverall={g['avgOverall']:<7} beats+0.2={str(g['beatsSummaryBy0.2']):<5} "
              f"ok={str(g['constraintsAllPass']):<5} dist={g['modeDistribution']}")
    print("\n=== Phase 2 · Leave-one-category-out ===")
    for l in search["leaveOneCategoryOut"]:
        print(f"  hold={l['heldOutCategory']:<13} t={l['chosenThreshold']} "
              f"test={l['testAvgOverall']} summary={l['testAlwaysSummary']} gain={l['testGainVsSummary']} "
              f"dist={l['testModeDistribution']}")

    # conclusion (step 11)
    proposed = policies["proposed-calibrated"]
    oracle_gain = oracle["oracleGainVsSummary"]
    verdict = (
        "auto SHOULD default to summary; benchmark evidence does not justify automatic full routing"
        if oracle_gain < 0.2 or not proposed["beatsSummaryBy0.2"] else
        "an interpretable policy beats always-summary within constraints"
    )
    print(f"\n=== Verdict ===\n{verdict}")
    print(f"(oracle gain {oracle_gain}; proposed beats summary by 0.2: {proposed['beatsSummaryBy0.2']})")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"oracle": oracle, "policies": policies, "search": search, "verdict": verdict}, f, indent=2)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
