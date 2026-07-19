"use client";

import { useRef, useState } from "react";

const mono = "var(--font-plex-mono), monospace";

type Status = "idle" | "loading" | "error";

const ERROR_MESSAGES: Record<string, string> = {
  not_authenticated: "Your session expired. Please sign in again.",
  not_found: "This report is no longer available.",
  too_large: "This report is too large to export.",
  rate_limited: "Too many exports. Please wait a moment.",
  backend_unavailable: "Export is temporarily unavailable.",
  export_failed: "The document could not be generated.",
};

function filenameFromDisposition(header: string | null): string {
  if (!header) return "evidentia-report.docx";
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      /* fall through to the plain form */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain?.[1] || "evidentia-report.docx";
}

/**
 * Authenticated "Download DOCX" control for a completed report page.
 *
 * The bytes are fetched from the BFF export route (which holds the httpOnly
 * session server-side — the browser never sees a token), streamed into a Blob,
 * and saved with the server-chosen filename. There is no localStorage copy of
 * the report, and no demo fallback: a failure is surfaced honestly.
 *
 * Concurrent clicks are ignored while a request is in flight, so a double-click
 * cannot fire two exports.
 */
export default function DownloadDocxButton({ reportId }: { reportId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [detail, setDetail] = useState<string>("");
  const inFlight = useRef(false);

  async function download() {
    // Guard against duplicate requests: a second click while busy is a no-op.
    if (inFlight.current) return;
    inFlight.current = true;
    setStatus("loading");
    setDetail("");

    try {
      const res = await fetch(`/api/reports/${encodeURIComponent(reportId)}/export/docx`, {
        method: "GET",
        cache: "no-store",
      });

      if (!res.ok) {
        let code = "export_failed";
        try {
          const body = (await res.json()) as { code?: string };
          if (body?.code) code = body.code;
        } catch {
          /* non-JSON error body */
        }
        setDetail(ERROR_MESSAGES[code] ?? ERROR_MESSAGES.export_failed);
        setStatus("error");
        return;
      }

      const blob = await res.blob();
      const filename = filenameFromDisposition(res.headers.get("content-disposition"));
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setStatus("idle");
    } catch {
      setDetail(ERROR_MESSAGES.backend_unavailable);
      setStatus("error");
    } finally {
      inFlight.current = false;
    }
  }

  const isError = status === "error";
  const isLoading = status === "loading";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      {isError && (
        <span
          role="alert"
          style={{ fontFamily: mono, fontSize: 11, color: "#c34635", maxWidth: 220, lineHeight: 1.3 }}
        >
          {detail}
        </span>
      )}
      <button
        type="button"
        onClick={download}
        disabled={isLoading}
        aria-busy={isLoading}
        title="Download an editable Word (.docx) version of this report"
        style={{
          fontFamily: "inherit",
          fontSize: 13,
          fontWeight: 600,
          color: "var(--ink)",
          background: "var(--paper)",
          border: `1px solid ${isError ? "#c34635" : "var(--line2)"}`,
          padding: "8px 15px",
          borderRadius: 8,
          cursor: isLoading ? "default" : "pointer",
          opacity: isLoading ? 0.65 : 1,
          display: "flex",
          alignItems: "center",
          gap: 8,
          whiteSpace: "nowrap",
        }}
      >
        <span style={{ width: 6, height: 6, borderRadius: 1, background: "var(--accent)" }} />
        {isLoading ? "Preparing…" : isError ? "Retry download" : "Download DOCX"}
      </button>
    </div>
  );
}
