"use client";

import type {
  CitationFeedbackVerdict,
  EvidentiaReport,
  ItemFeedbackVerdict,
  ReportFeedbackSnapshot,
  ReportFeedbackVerdict,
  ReportSourceAudit,
} from "./types";

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

export async function fetchReportFeedback(id: string): Promise<ReportFeedbackSnapshot | null> {
  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(id)}/feedback`, { cache: "no-store" });
    if (!res.ok) return null;
    const data = (await res.json()) as ReportFeedbackSnapshot;
    return data && Array.isArray(data.items) && Array.isArray(data.citations) ? data : null;
  } catch {
    return null;
  }
}

async function putFeedback(path: string, body: unknown): Promise<boolean> {
  try {
    const res = await fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function putReportFeedback(
  id: string,
  verdict: ReportFeedbackVerdict,
  privateText?: string,
): Promise<boolean> {
  return putFeedback(`/api/reports/${encodeURIComponent(id)}/feedback`, {
    verdict,
    privateText: privateText?.trim() || null,
  });
}

export function putItemFeedback(
  id: string,
  itemPath: string,
  itemType: "workflow_step" | "risk" | "citation" | "suggested_action",
  verdict: ItemFeedbackVerdict,
): Promise<boolean> {
  return putFeedback(`/api/reports/${encodeURIComponent(id)}/feedback/items`, {
    itemPath,
    itemType,
    verdict,
  });
}

export function putCitationFeedback(
  id: string,
  itemPath: string,
  citationId: string,
  verdict: CitationFeedbackVerdict,
): Promise<boolean> {
  return putFeedback(`/api/reports/${encodeURIComponent(id)}/feedback/citations`, {
    itemPath,
    citationId,
    verdict,
  });
}
