import { runEvidentiaAgents } from "@/lib/agents/orchestrator";
import type { EvidentiaReport } from "@/lib/types";
import { SCENARIOS, getScenario } from "./scenarios";

/**
 * Static fallback reports generated deterministically from the demo scenarios.
 * Used to seed the Reports and Playbooks libraries when localStorage is empty.
 */
export const DEMO_REPORTS: EvidentiaReport[] = SCENARIOS.map((s) =>
  runEvidentiaAgents(s.input),
);

export function getDemoReport(id: string): EvidentiaReport | undefined {
  return DEMO_REPORTS.find((r) => r.id === id);
}

/** Generate a report for a scenario id, or fall back to a default run. */
export function generateReportForId(id: string): EvidentiaReport {
  const scenario = getScenario(id);
  if (scenario) return runEvidentiaAgents(scenario.input);
  const existing = getDemoReport(id);
  if (existing) return existing;
  // Default deterministic report for unknown / "current" ids without storage.
  return runEvidentiaAgents({
    market: "EMEA",
    persona: "Support Agent",
    customPersona: "",
    selectedDocumentIds: [],
    id,
  });
}
