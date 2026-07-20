import type { AgentInput } from "./types";

/** Versioned so pending runs containing bundled document ids are ignored. */
export const PENDING_RUN_KEY = "evidentia:tenant-pending-run:v2";

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
    /* ignore unavailable browser storage */
  }
  return pendingRun;
}

export function readPendingRun(): PendingRun | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(PENDING_RUN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PendingRun;
    if (
      typeof parsed.id === "string" &&
      parsed.input &&
      typeof parsed.input === "object" &&
      Array.isArray(parsed.input.selectedDocumentIds) &&
      parsed.input.selectedDocumentIds.length > 0 &&
      parsed.input.selectedDocumentIds.every(
        (id) => typeof id === "string" && id.length > 0,
      )
    ) {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}
