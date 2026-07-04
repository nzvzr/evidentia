"use client";

import { useCallback, useEffect, useState } from "react";
import type { AppSettings } from "./types";

const STORAGE_KEY = "evidentia:settings";

export const DEFAULT_SETTINGS: AppSettings = {
  workspaceName: "Northreach Cloud · EMEA",
  defaultMarket: "EMEA",
  defaultPersona: "Solutions Architect",
  exportFormat: "US Letter",
  theme: "System",
};

function readSettings(): AppSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<AppSettings>) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);

  useEffect(() => {
    setSettings(readSettings());
  }, []);

  const save = useCallback((next: AppSettings) => {
    setSettings(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }, []);

  return { settings, save };
}
