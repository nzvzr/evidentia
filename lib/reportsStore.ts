"use client";

import type { EvidentiaReport } from "./types";

const STORAGE_KEY = "evidentia:reports";
const MAX_REPORTS = 30;

function read(): EvidentiaReport[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as EvidentiaReport[]) : [];
  } catch {
    return [];
  }
}

function write(reports: EvidentiaReport[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(reports.slice(0, MAX_REPORTS)));
  } catch {
    /* ignore quota / serialization errors */
  }
}

/** Persist a report (newest first, de-duplicated by id). */
export function saveReport(report: EvidentiaReport): void {
  const existing = read().filter((r) => r.id !== report.id);
  write([report, ...existing]);
}

export function getReport(id: string): EvidentiaReport | null {
  return read().find((r) => r.id === id) ?? null;
}

export function getReports(): EvidentiaReport[] {
  return read();
}

export function getLastReport(): EvidentiaReport | null {
  const all = read();
  return all.length > 0 ? all[0] : null;
}

export function clearReports(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Resolve a report by id for the detail / print pages.
 * Order: localStorage → demo scenario/default. This is safe to call after mount.
 */
export function resolveStoredReport(
  id: string,
  fallback: (id: string) => EvidentiaReport,
): EvidentiaReport {
  const stored = getReport(id);
  if (stored) return stored;
  if (id === "current") {
    const last = getLastReport();
    if (last) return last;
  }
  return fallback(id);
}
