"use client";

import { PUBLIC_DEMO_PREFIX } from "./sessionCache";
import type { EvidentiaReport } from "./types";

/**
 * Storage for the **public demo** report only.
 *
 * This module used to cache every authenticated report under a global
 * `evidentia:reports` key that survived logout. It no longer touches
 * authenticated data at all: a signed-in user's reports live in the backend and
 * are fetched per request (lib/reportsApi.ts).
 *
 * The single key here holds the anonymous sample report produced by
 * `/api/demo/generate-workflow`, so the public demo can navigate from the run
 * page to the report page without a backend. It contains no customer data.
 */

const DEMO_REPORT_KEY = `${PUBLIC_DEMO_PREFIX}report`;

/** Persist the public demo report. Never call this with an authenticated report. */
export function saveDemoReport(report: EvidentiaReport): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(DEMO_REPORT_KEY, JSON.stringify(report));
  } catch {
    /* ignore quota / serialization errors */
  }
}

export function getDemoReport(): EvidentiaReport | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(DEMO_REPORT_KEY);
    return raw ? (JSON.parse(raw) as EvidentiaReport) : null;
  } catch {
    return null;
  }
}

export function clearDemoReport(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(DEMO_REPORT_KEY);
  } catch {
    /* ignore */
  }
}
