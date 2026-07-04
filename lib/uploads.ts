"use client";

import { useCallback, useEffect, useState } from "react";
import type { UploadedDoc } from "./types";

const STORAGE_KEY = "evidentia:uploaded-documents";

export function readUploads(): UploadedDoc[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as UploadedDoc[]) : [];
  } catch {
    return [];
  }
}

function writeUploads(docs: UploadedDoc[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(docs));
  } catch {
    /* ignore */
  }
}

function kindFromName(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase();
  if (ext === "md") return "MD";
  if (ext === "txt") return "TXT";
  return "TXT";
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Session-only uploads processed entirely client-side (no server). */
export function useUploads() {
  const [uploads, setUploads] = useState<UploadedDoc[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setUploads(readUploads());
    setHydrated(true);
  }, []);

  const addFile = useCallback(async (file: File) => {
    const text = await file.text();
    const excerpt = text.replace(/\s+/g, " ").trim().slice(0, 220) || "(empty document)";
    const doc: UploadedDoc = {
      id: `up-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      name: file.name.replace(/\.(md|txt)$/i, ""),
      filename: file.name,
      kind: kindFromName(file.name),
      category: "Session upload",
      sizeLabel: sizeLabel(file.size),
      uploadedAt: new Date().toLocaleDateString("en-US", {
        month: "short",
        day: "2-digit",
        year: "numeric",
      }),
      excerpt,
      status: "Indexed (session)",
    };
    setUploads((prev) => {
      const next = [doc, ...prev];
      writeUploads(next);
      return next;
    });
    return doc;
  }, []);

  const remove = useCallback((id: string) => {
    setUploads((prev) => {
      const next = prev.filter((d) => d.id !== id);
      writeUploads(next);
      return next;
    });
  }, []);

  return { uploads, hydrated, addFile, remove };
}
