import type { AgentInput } from "./types";

/** localStorage key holding the pipeline input for the pending run. */
export const PENDING_RUN_KEY = "evidentia:pending-run";

export interface PendingRun {
  /** A fresh, non-secret nonce for one click/retry. */
  id: string;
  input: AgentInput;
}

function newRunId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createPendingRun(input: AgentInput): PendingRun {
  return { id: newRunId(), input };
}

export function writePendingRun(input: AgentInput): PendingRun {
  const pendingRun = createPendingRun(input);
  if (typeof window === "undefined") return pendingRun;
  try {
    window.localStorage.setItem(PENDING_RUN_KEY, JSON.stringify(pendingRun));
  } catch {
    /* ignore */
  }
  return pendingRun;
}

export function readPendingRun(): PendingRun | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(PENDING_RUN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PendingRun | AgentInput;
    if (
      typeof (parsed as PendingRun).id === "string" &&
      (parsed as PendingRun).input &&
      typeof (parsed as PendingRun).input === "object"
    ) {
      return parsed as PendingRun;
    }

    // One-release compatibility for a run started by the previous frontend.
    return createPendingRun(parsed as AgentInput);
  } catch {
    return null;
  }
}
