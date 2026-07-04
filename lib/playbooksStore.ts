"use client";

import type { DerivedReport } from "./demoReport";
import type { PlaybookRecord, WorkspaceSelection } from "./types";

const STORAGE_KEY = "evidentia:last-report";

export function readLastReport(): PlaybookRecord | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PlaybookRecord) : null;
  } catch {
    return null;
  }
}

export function writeLastReport(record: PlaybookRecord): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(record));
  } catch {
    /* ignore */
  }
}

/** Build a persisted playbook record from a derived report + selection. */
export function recordFromReport(
  report: DerivedReport,
  selection: WorkspaceSelection,
): PlaybookRecord {
  return {
    id: "current",
    title: `${report.personaTitle} · ${report.marketLabel}`,
    company: report.company,
    persona: report.personaTitle,
    market: report.marketLabel,
    generatedDate: "Jul 04 2026",
    confidence: report.confidence,
    risks: 4,
    citations: report.nCitations,
    documents: report.nDocs,
    exportStatus: "Ready",
    templateType: "Custom run",
    category: "All",
    selection,
  };
}
