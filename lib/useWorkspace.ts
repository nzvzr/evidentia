"use client";

import { useCallback, useEffect, useState } from "react";
import { DEFAULT_PICKED } from "./demoDocs";
import type { DocId, WorkspaceSelection } from "./types";

const STORAGE_KEY = "evidentia:workspace";

export const DEFAULT_SELECTION: WorkspaceSelection = {
  picked: DEFAULT_PICKED,
  market: "EMEA",
  persona: "architect",
  custom: "",
};

export function readSelection(): WorkspaceSelection {
  if (typeof window === "undefined") return DEFAULT_SELECTION;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SELECTION;
    const parsed = JSON.parse(raw) as Partial<WorkspaceSelection>;
    return {
      picked: Array.isArray(parsed.picked) ? (parsed.picked as DocId[]) : DEFAULT_SELECTION.picked,
      market: typeof parsed.market === "string" ? parsed.market : DEFAULT_SELECTION.market,
      persona: typeof parsed.persona === "string" ? parsed.persona : DEFAULT_SELECTION.persona,
      custom: typeof parsed.custom === "string" ? parsed.custom : "",
    };
  } catch {
    return DEFAULT_SELECTION;
  }
}

export function writeSelection(selection: WorkspaceSelection): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
  } catch {
    /* ignore */
  }
}

/**
 * Reads the persisted workspace selection on the client.
 * `hydrated` is false during SSR / first paint so consumers can avoid
 * hydration mismatches by rendering defaults until it flips true.
 */
export function useWorkspaceSelection() {
  const [selection, setSelection] = useState<WorkspaceSelection>(DEFAULT_SELECTION);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setSelection(readSelection());
    setHydrated(true);
  }, []);

  const update = useCallback((next: WorkspaceSelection) => {
    setSelection(next);
    writeSelection(next);
  }, []);

  return { selection, setSelection: update, hydrated };
}
