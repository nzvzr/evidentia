"use client";

import { useCallback, useEffect, useState } from "react";
import type { UploadedDoc } from "./types";

/**
 * Uploaded documents — backend-persisted, tenant-scoped.
 *
 * These used to live in a global `evidentia:uploaded-documents` localStorage key
 * holding the text excerpt of every file the user uploaded. That key was never
 * cleared on logout, so one account's document content stayed readable in the
 * browser and was shown to whoever signed in next.
 *
 * They now go to `POST /api/documents`, which stores them against the
 * authenticated user's company. The backend is the only source of truth; nothing
 * is mirrored into localStorage.
 */

function kindFromName(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase();
  if (ext === "md") return "MD";
  return "TXT";
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface BackendDoc {
  id: string;
  companyId?: string;
  title: string;
  type?: string | null;
  category?: string | null;
  createdAt?: string | null;
  metadata?: Record<string, unknown> | null;
}

function toUploadedDoc(raw: BackendDoc): UploadedDoc {
  const meta = raw.metadata ?? {};
  return {
    id: raw.id,
    name: raw.title,
    filename: String(meta.filename ?? raw.title),
    kind: raw.type ?? "TXT",
    category: raw.category ?? "Uploaded",
    sizeLabel: String(meta.sizeLabel ?? ""),
    uploadedAt: raw.createdAt
      ? new Date(raw.createdAt).toLocaleDateString("en-US", {
          month: "short",
          day: "2-digit",
          year: "numeric",
        })
      : "",
    excerpt: String(meta.excerpt ?? ""),
    status: "Indexed",
  };
}

/** Client-side guard; the backend caps the request body independently. */
const MAX_UPLOAD_BYTES = 200_000;

export function useUploads() {
  const [uploads, setUploads] = useState<UploadedDoc[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/documents", { cache: "no-store" });
      if (!res.ok) {
        setUploads([]);
        return;
      }
      const data = await res.json();
      // Only tenant-owned rows (the built-in demo corpus has no companyId).
      const docs: UploadedDoc[] = (data?.documents ?? [])
        .filter((d: BackendDoc) => Boolean(d?.companyId))
        .map(toUploadedDoc);
      setUploads(docs);
    } catch {
      setUploads([]);
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const addFile = useCallback(
    async (file: File) => {
      setError(null);
      if (file.size > MAX_UPLOAD_BYTES) {
        setError("That file is too large (max 200 KB).");
        return null;
      }

      const text = await file.text();
      const excerpt = text.replace(/\s+/g, " ").trim().slice(0, 220) || "(empty document)";

      const res = await fetch("/api/documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: file.name.replace(/\.(md|txt)$/i, ""),
          type: kindFromName(file.name),
          category: "Uploaded",
          contentText: text.slice(0, MAX_UPLOAD_BYTES),
          metadata: { filename: file.name, sizeLabel: sizeLabel(file.size), excerpt },
        }),
      });

      if (!res.ok) {
        setError(res.status === 401 ? "Please sign in again." : "Upload failed.");
        return null;
      }

      const created = toUploadedDoc(await res.json());
      await refresh();
      return created;
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

  return { uploads, hydrated, error, addFile, remove, refresh };
}
