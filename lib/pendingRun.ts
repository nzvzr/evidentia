import type { AgentInput } from "./types";

/** localStorage key holding the pipeline input for the pending run. */
export const PENDING_RUN_KEY = "evidentia:pending-run";

export function writePendingRun(input: AgentInput): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(PENDING_RUN_KEY, JSON.stringify(input));
  } catch {
    /* ignore */
  }
}

export function readPendingRun(): AgentInput | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(PENDING_RUN_KEY);
    return raw ? (JSON.parse(raw) as AgentInput) : null;
  } catch {
    return null;
  }
}
