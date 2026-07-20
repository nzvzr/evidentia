"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Tenant documents for the Documents page.
 *
 * The backend's `tenantCorpus` config on GET /api/documents gates real
 * multipart uploads, per-document ingestion state, retry/new-version actions,
 * and a bounded status poll while a tenant document is processing. When that
 * config is absent or disabled, callers receive an explicit unavailable state;
 * this hook never creates or persists a browser-local substitute.
 *
 * Nothing is cached in localStorage; the backend is the only source of truth.
 */

export interface IngestionState {
  status: string;
  stage: string | null;
  /** M3: what the latest version's work is — "ingest" or "finalize". */
  stageKind: string | null;
  /** M3: identity of the current version — "transitional" | "final" | null. */
  identity: string | null;
  /** M3: current version is final AND ready (citation-ready). */
  finalized: boolean;
  /** Exact M3 predicate passed; safe to use for authenticated generation. */
  generationEligible: boolean;
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
  generationEnabled: boolean;
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
export const ACTIVE_STAGES = new Set([
  "pending",
  "extracting",
  "sectioning",
  "anchoring",
  "classifying",
]);

export const POLL_INTERVAL_MS = 2_500;

function toIngestion(raw: Partial<IngestionState> | null | undefined): IngestionState | null {
  if (!raw) return null;
  return {
    status: String(raw.status ?? ""),
    stage: raw.stage != null ? String(raw.stage) : null,
    stageKind: raw.stageKind != null ? String(raw.stageKind) : null,
    identity: raw.identity != null ? String(raw.identity) : null,
    finalized: Boolean(raw.finalized),
    generationEligible: Boolean(raw.generationEligible),
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
    case "not_finalizable":
    case "no_ready_version":
      return "This document is not ready to be finalized yet.";
    case "already_final":
      return "This document is already citation-ready.";
    case "backend_unavailable":
      return "Upload is unavailable right now. Please try again later.";
    default:
      break;
  }
  if (status === 401) return "Please sign in again.";
  if (status === 429) return "Too many uploads. Please try again later.";
  return "Upload failed.";
}

export function useTenantDocuments() {
  const [documents, setDocuments] = useState<TenantDocument[]>([]);
  const [corpus, setCorpus] = useState<TenantCorpusConfig | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [loadError, setLoadError] = useState(false);

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
        setCorpus(null);
        setLoadError(true);
        return;
      }
      const data = await res.json();
      if (!mountedRef.current || seq !== seqRef.current) return;
      const docs: TenantDocument[] = (data?.documents ?? [])
        .filter((d: BackendDoc) => Boolean(d?.companyId))
        .map(toTenantDocument);
      setDocuments(docs);
      setLoadError(false);
      const cfg = data?.tenantCorpus;
      setCorpus(
        cfg && typeof cfg === "object"
          ? {
              enabled: Boolean(cfg.enabled),
              generationEnabled: Boolean(cfg.generationEnabled),
              acceptedExtensions: Array.isArray(cfg.acceptedExtensions)
                ? cfg.acceptedExtensions.map(String)
                : [".md", ".txt"],
              maxFileBytes: Number(cfg.maxFileBytes) || 0,
            }
          : null,
      );
    } catch {
      if (mountedRef.current && seq === seqRef.current) {
        setDocuments([]);
        setCorpus(null);
        setLoadError(true);
      }
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

  /** Trigger M3 finalization of a parsed (transitional) document. Idempotent:
   * repeats adopt the live finalization instead of duplicating it. */
  const finalize = useCallback(
    async (documentId: string): Promise<UploadResult> => {
      try {
        const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}/finalize`, {
          method: "POST",
        });
        return await parseUploadResponse(res);
      } catch {
        return { ok: false, error: "Finalization is unavailable right now. Please try again later." };
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
    loadError,
    hydrated,
    uploading,
    anyProcessing,
    refresh,
    uploadFile,
    uploadNewVersion,
    finalize,
    retry,
    remove,
  };
}
