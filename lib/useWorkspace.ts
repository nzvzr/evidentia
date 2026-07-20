"use client";

import { useCallback, useEffect, useState } from "react";
import type { WorkspaceSelection } from "./types";

/** Versioned so bundled-document selections from older builds cannot reappear. */
export const WORKSPACE_STORAGE_KEY = "evidentia:tenant-workspace:v2";

export const DEFAULT_SELECTION: WorkspaceSelection = {
  picked: [],
  market: "EMEA",
  persona: "architect",
  custom: "",
};

export function readSelection(): WorkspaceSelection {
  if (typeof window === "undefined") return DEFAULT_SELECTION;
  try {
    const raw = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (!raw) return DEFAULT_SELECTION;
    const parsed = JSON.parse(raw) as Partial<WorkspaceSelection>;
    return {
      picked: Array.isArray(parsed.picked)
        ? parsed.picked.filter((id): id is string => typeof id === "string")
        : [],
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
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(selection));
  } catch {
    /* ignore unavailable browser storage */
  }
}

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
