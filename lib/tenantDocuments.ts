"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { UploadedDoc } from "./types";

/**
 * Tenant documents for the Documents page.
 *
 * One hook serves both feature states, driven by the backend's additive
 * `tenantCorpus` config on GET /api/documents:
 *
 * - **Tenant corpus enabled** — real multipart uploads
 *   (`POST /api/documents/upload`), per-document ingestion state from the
 *   backend's `ingestion` metadata, retry / new-version actions, and a
 *   bounded, lifecycle-safe status poll that runs only while a document is
 *   actively processing.
 * - **Disabled (default)** — the pre-M2 behavior: JSON document creation via
 *   `POST /api/documents` with a local text excerpt, no ingestion claims.
 *
 * Nothing is cached in localStorage; the backend is the only source of truth.
 */

export interface IngestionState {
  status: string;
  stage: string | null;
  versionNo: number | null;
  filename: string | null;
  detectedFormat: string | null;
  byteSize: number | null;
  sectionCount: number | null;
  errorCode: string | null;
  errorMessage: string | null;
  updatedAt: string | null;
  sourceType: string | null;
}

export interface TenantDocument {
  id: string;
  title: string;
  type: string | null;
  category: string | null;
  createdAt: string | null;
  metadata: Record<string, unknown> | null;
  ingestion: IngestionState | null;
}

export interface TenantCorpusConfig {
  enabled: boolean;
  acceptedExtensions: string[];
  maxFileBytes: number;
}

export interface UploadResult {
  ok: boolean;
  /** true when the backend reported an explicit duplicate or no-op */
  duplicate?: boolean;
  noop?: boolean;
  retried?: boolean;
  error?: string;
}

interface BackendDoc {
  id: string;
  companyId?: string;
  title: string;
  type?: string | null;
  category?: string | null;
  createdAt?: string | null;
  metadata?: Record<string, unknown> | null;
  ingestion?: Partial<IngestionState> | null;
}

/** Ingestion stages that mean "still processing" — the only states we poll for. */
export const ACTIVE_STAGES = new Set(["pending", "extracting", "sectioning"]);

export const POLL_INTERVAL_MS = 2_500;

function toIngestion(raw: Partial<IngestionState> | null | undefined): IngestionState | null {
  if (!raw) return null;
  return {
    status: String(raw.status ?? ""),
    stage: raw.stage != null ? String(raw.stage) : null,
    versionNo: typeof raw.versionNo === "number" ? raw.versionNo : null,
    filename: raw.filename != null ? String(raw.filename) : null,
    detectedFormat: raw.detectedFormat != null ? String(raw.detectedFormat) : null,
    byteSize: typeof raw.byteSize === "number" ? raw.byteSize : null,
    sectionCount: typeof raw.sectionCount === "number" ? raw.sectionCount : null,
    errorCode: raw.errorCode != null ? String(raw.errorCode) : null,
    errorMessage: raw.errorMessage != null ? String(raw.errorMessage) : null,
    updatedAt: raw.updatedAt != null ? String(raw.updatedAt) : null,
    sourceType: raw.sourceType != null ? String(raw.sourceType) : null,
  };
}

function toTenantDocument(raw: BackendDoc): TenantDocument {
  return {
    id: raw.id,
    title: raw.title,
    type: raw.type ?? null,
    category: raw.category ?? null,
    createdAt: raw.createdAt ?? null,
    metadata: raw.metadata ?? null,
    ingestion: toIngestion(raw.ingestion),
  };
}

export function isProcessing(doc: TenantDocument): boolean {
  const stage = doc.ingestion?.stage;
  return stage != null && ACTIVE_STAGES.has(stage);
}

export function sizeLabel(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Map a typed backend rejection to a user-facing message. */
function uploadErrorMessage(status: number, code: string | undefined): string {
  switch (code) {
    case "tenant_corpus_disabled":
      return "Document upload is not enabled for this deployment.";
    case "unsupported_extension":
    case "unsupported_type":
    case "type_mismatch":
      return "Only .md and .txt files are supported.";
    case "file_too_large":
    case "payload_too_large":
    case "extraction_too_large":
      return "That file is too large.";
    case "empty_file":
      return "That file is empty.";
    case "invalid_encoding":
      return "That file is not valid UTF-8 text.";
    case "document_quota_exceeded":
      return "Your organization has reached its document limit.";
    case "storage_quota_exceeded":
      return "Your organization has reached its storage limit.";
    case "rate_limited":
      return "Too many uploads. Please try again later.";
    case "version_not_failed":
      return "Only a failed document can be retried.";
    case "backend_unavailable":
      return "Upload is unavailable right now. Please try again later.";
    default:
      break;
  }
  if (status === 401) return "Please sign in again.";
  if (status === 429) return "Too many uploads. Please try again later.";
  return "Upload failed.";
}

/** Legacy display mapping (pre-M2 path, corpus disabled). */
export function toLegacyUploadedDoc(doc: TenantDocument): UploadedDoc {
  const meta = doc.metadata ?? {};
  return {
    id: doc.id,
    name: doc.title,
    filename: String(meta.filename ?? doc.title),
    kind: doc.type ?? "TXT",
    category: doc.category ?? "Uploaded",
    sizeLabel: String(meta.sizeLabel ?? ""),
    uploadedAt: doc.createdAt
      ? new Date(doc.createdAt).toLocaleDateString("en-US", {
          month: "short",
          day: "2-digit",
          year: "numeric",
        })
      : "",
    excerpt: String(meta.excerpt ?? ""),
    status: "Indexed",
  };
}

/** Client-side guard for the legacy JSON path; the backend caps independently. */
const LEGACY_MAX_UPLOAD_BYTES = 200_000;

export function useTenantDocuments() {
  const [documents, setDocuments] = useState<TenantDocument[]>([]);
  const [corpus, setCorpus] = useState<TenantCorpusConfig | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Stale-response guard: only the newest in-flight refresh may write state.
  const seqRef = useRef(0);
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      const res = await fetch("/api/documents", { cache: "no-store" });
      if (!mountedRef.current || seq !== seqRef.current) return;
      if (!res.ok) {
        setDocuments([]);
        return;
      }
      const data = await res.json();
      if (!mountedRef.current || seq !== seqRef.current) return;
      const docs: TenantDocument[] = (data?.documents ?? [])
        .filter((d: BackendDoc) => Boolean(d?.companyId))
        .map(toTenantDocument);
      setDocuments(docs);
      const cfg = data?.tenantCorpus;
      setCorpus(
        cfg && typeof cfg === "object"
          ? {
              enabled: Boolean(cfg.enabled),
              acceptedExtensions: Array.isArray(cfg.acceptedExtensions)
                ? cfg.acceptedExtensions.map(String)
                : [".md", ".txt"],
              maxFileBytes: Number(cfg.maxFileBytes) || 0,
            }
          : null,
      );
    } catch {
      if (mountedRef.current && seq === seqRef.current) setDocuments([]);
    } finally {
      if (mountedRef.current && seq === seqRef.current) setHydrated(true);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
    };
  }, [refresh]);

  // Bounded status polling: only while at least one document is actively
  // processing; interval cleared on terminal states and on unmount. Strict
  // Mode replay is safe because the effect fully cleans up its interval.
  const anyProcessing = documents.some(isProcessing);
  useEffect(() => {
    if (!anyProcessing) return;
    const timer = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [anyProcessing, refresh]);

  const parseUploadResponse = useCallback(
    async (res: Response): Promise<UploadResult> => {
      const body = await res.json().catch(() => ({} as Record<string, unknown>));
      if (res.ok) {
        await refresh();
        return {
          ok: true,
          duplicate: Boolean((body as Record<string, unknown>).duplicate),
          noop: Boolean((body as Record<string, unknown>).noop),
          retried: Boolean((body as Record<string, unknown>).retried),
        };
      }
      const code =
        typeof (body as Record<string, unknown>).code === "string"
          ? String((body as Record<string, unknown>).code)
          : undefined;
      return { ok: false, error: uploadErrorMessage(res.status, code) };
    },
    [refresh],
  );

  /** Real multipart upload (corpus enabled). */
  const uploadFile = useCallback(
    async (file: File): Promise<UploadResult> => {
      setUploading(true);
      try {
        const form = new FormData();
        form.append("file", file, file.name);
        const res = await fetch("/api/documents/upload", { method: "POST", body: form });
        return await parseUploadResponse(res);
      } catch {
        return { ok: false, error: "Upload is unavailable right now. Please try again later." };
      } finally {
        setUploading(false);
      }
    },
    [parseUploadResponse],
  );

  /** Explicit new version for an existing tenant document. */
  const uploadNewVersion = useCallback(
    async (documentId: string, file: File): Promise<UploadResult> => {
      setUploading(true);
      try {
        const form = new FormData();
        form.append("file", file, file.name);
        const res = await fetch(
          `/api/documents/${encodeURIComponent(documentId)}/versions`,
          { method: "POST", body: form },
        );
        return await parseUploadResponse(res);
      } catch {
        return { ok: false, error: "Upload is unavailable right now. Please try again later." };
      } finally {
        setUploading(false);
      }
    },
    [parseUploadResponse],
  );

  /** Retry a failed ingestion (reuses the stored bytes; no duplicates). */
  const retry = useCallback(
    async (documentId: string): Promise<UploadResult> => {
      try {
        const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}/retry`, {
          method: "POST",
        });
        return await parseUploadResponse(res);
      } catch {
        return { ok: false, error: "Retry is unavailable right now. Please try again later." };
      }
    },
    [parseUploadResponse],
  );

  /** Legacy JSON creation (corpus disabled) — the pre-M2 behavior, unchanged. */
  const addLegacyFile = useCallback(
    async (file: File): Promise<UploadResult> => {
      if (file.size > LEGACY_MAX_UPLOAD_BYTES) {
        return { ok: false, error: "That file is too large (max 200 KB)." };
      }
      const text = await file.text();
      const excerpt = text.replace(/\s+/g, " ").trim().slice(0, 220) || "(empty document)";
      const ext = file.name.split(".").pop()?.toLowerCase();
      try {
        const res = await fetch("/api/documents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: file.name.replace(/\.(md|txt)$/i, ""),
            type: ext === "md" ? "MD" : "TXT",
            category: "Uploaded",
            contentText: text.slice(0, LEGACY_MAX_UPLOAD_BYTES),
            metadata: {
              filename: file.name,
              sizeLabel: sizeLabel(file.size),
              excerpt,
            },
          }),
        });
        if (!res.ok) {
          return {
            ok: false,
            error: res.status === 401 ? "Please sign in again." : "Upload failed.",
          };
        }
        await refresh();
        return { ok: true };
      } catch {
        return { ok: false, error: "Upload failed." };
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      await fetch(`/api/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
      await refresh();
    },
    [refresh],
  );

  return {
    documents,
    corpus,
    corpusEnabled: Boolean(corpus?.enabled),
    hydrated,
    uploading,
    anyProcessing,
    refresh,
    uploadFile,
    uploadNewVersion,
    retry,
    addLegacyFile,
    remove,
  };
}
