"use client";

import type { EvidentiaReport, ReportSourceAudit } from "./types";

function looksLikeReport(data: unknown): data is EvidentiaReport {
  return !!data && typeof data === "object" && "id" in data && "metrics" in data;
}

/** Fetch a single persisted report via the Next proxy. Returns null if absent. */
export async function fetchBackendReport(id: string): Promise<EvidentiaReport | null> {
  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(id)}`, { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    return looksLikeReport(data) ? data : null;
  } catch {
    return null;
  }
}

/** Fetch persisted reports via the Next proxy. Returns [] if unavailable. */
export async function fetchBackendReports(): Promise<EvidentiaReport[]> {
  try {
    const res = await fetch("/api/reports", { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data?.reports) ? (data.reports as EvidentiaReport[]) : [];
  } catch {
    return [];
  }
}

export async function fetchReportSourceAudit(id: string): Promise<ReportSourceAudit | null> {
  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(id)}/sources`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as ReportSourceAudit;
    return data && Array.isArray(data.evidenceBindings) ? data : null;
  } catch {
    return null;
  }
}
