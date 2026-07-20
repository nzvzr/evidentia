"use client";

import { useMemo, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import {
  isProcessing,
  sizeLabel,
  useTenantDocuments,
  type TenantDocument,
} from "@/lib/tenantDocuments";

const mono = "var(--font-plex-mono), monospace";

function stageLabel(doc: TenantDocument): string {
  const ingestion = doc.ingestion;
  switch (ingestion?.stage) {
    case "pending":
      return "Queued";
    case "extracting":
      return "Extracting";
    case "sectioning":
      return "Sectioning";
    case "anchoring":
      return "Anchoring";
    case "classifying":
      return "Classifying";
    case "ready":
      return ingestion.generationEligible
        ? "Citation-ready"
        : ingestion.finalized
          ? "Finalized · unavailable"
          : "Awaiting finalization";
    case "failed":
      return ingestion.stageKind === "finalize" ? "Finalization failed" : "Failed";
    default:
      return ingestion?.status === "processing" ? "Processing" : "Stored";
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  });
}

export default function DocumentsPage() {
  const {
    documents,
    corpus,
    corpusEnabled,
    loadError,
    hydrated,
    uploading,
    uploadFile,
    uploadNewVersion,
    finalize,
    retry,
    remove,
  } = useTenantDocuments();

  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const versionFileRef = useRef<HTMLInputElement>(null);
  const versionTargetRef = useRef<string | null>(null);

  const stats = useMemo(
    () => ({
      documents: documents.length,
      ready: documents.filter((doc) => doc.ingestion?.generationEligible).length,
      processing: documents.filter(isProcessing).length,
      sections: documents.reduce(
        (total, doc) => total + (doc.ingestion?.sectionCount ?? 0),
        0,
      ),
    }),
    [documents],
  );

  const maxSizeLabel = corpus?.maxFileBytes ? sizeLabel(corpus.maxFileBytes) : "2.0 MB";

  const validSelection = (file: File): boolean => {
    if (!/\.(txt|md)$/i.test(file.name)) {
      setUploadError("Only .md and .txt files are supported.");
      return false;
    }
    return true;
  };

  const onFiles = async (files: FileList | null) => {
    if (!corpusEnabled || !files || files.length === 0) return;
    setUploadError(null);
    setUploadNotice(null);
    if (files.length > 1) {
      setUploadError("Upload one file at a time.");
      return;
    }
    const file = files[0];
    if (!validSelection(file)) return;
    const result = await uploadFile(file);
    if (!result.ok) setUploadError(result.error ?? "Upload failed.");
    else if (result.duplicate) setUploadNotice("Already in your library — nothing new was stored.");
    else if (result.noop) setUploadNotice("Identical to the current version — no new version was created.");
    else setUploadNotice("Upload accepted — processing has started.");
    if (fileRef.current) fileRef.current.value = "";
  };

  const onVersionFile = async (files: FileList | null) => {
    const targetId = versionTargetRef.current;
    versionTargetRef.current = null;
    if (!files || files.length === 0 || !targetId) return;
    setUploadError(null);
    setUploadNotice(null);
    const file = files[0];
    if (!validSelection(file)) return;
    const result = await uploadNewVersion(targetId, file);
    if (!result.ok) setUploadError(result.error ?? "Upload failed.");
    else if (result.noop) setUploadNotice("Identical to the current version — no new version was created.");
    else if (result.retried) setUploadNotice("Retrying the failed version with the same content.");
    else setUploadNotice("New version accepted — processing has started.");
    if (versionFileRef.current) versionFileRef.current.value = "";
  };

  const onRetry = async (documentId: string) => {
    setUploadError(null);
    setUploadNotice(null);
    const result = await retry(documentId);
    if (!result.ok) setUploadError(result.error ?? "Retry failed.");
    else setUploadNotice("Retry started.");
  };

  const onFinalize = async (documentId: string) => {
    setUploadError(null);
    setUploadNotice(null);
    const result = await finalize(documentId);
    if (!result.ok) setUploadError(result.error ?? "Finalization failed to start.");
    else setUploadNotice("Finalization started — anchors and classification are being computed.");
  };

  return (
    <AppShell active="documents">
      <div style={headerBar}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <span style={{ fontWeight: 700, fontSize: 14.5 }}>Documents</span>
          <span style={{ color: "var(--line2)" }}>/</span>
          <span style={{ fontSize: 13.5, color: "var(--sub)" }}>Tenant corpus</span>
        </div>
        <button
          onClick={() => fileRef.current?.click()}
          style={primaryBtn}
          disabled={uploading || !corpusEnabled}
        >
          <span style={{ fontSize: 15, lineHeight: 1 }}>+</span>
          {uploading ? "Uploading…" : "Upload document"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.md,text/plain,text/markdown"
          disabled={!corpusEnabled}
          onChange={(event) => void onFiles(event.target.files)}
          style={{ display: "none" }}
        />
        <input
          ref={versionFileRef}
          type="file"
          accept=".txt,.md,text/plain,text/markdown"
          aria-label="New version file"
          onChange={(event) => void onVersionFile(event.target.files)}
          style={{ display: "none" }}
        />
      </div>

      <div style={{ maxWidth: 1240, width: "100%", margin: "0 auto", padding: "32px 40px 64px" }}>
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>Documents</h1>
          <p style={{ fontSize: 14.5, color: "var(--sub)", margin: "9px 0 0", lineHeight: 1.5 }}>
            Manage the authenticated organization corpus used for evidence-backed reports.
          </p>
        </div>

        <div style={statGrid} className="ev-stat-grid">
          <Stat label="Tenant documents" value={hydrated ? String(stats.documents) : "—"} />
          <Stat label="Citation-ready" value={hydrated ? String(stats.ready) : "—"} accent />
          <Stat label="Processing" value={hydrated ? String(stats.processing) : "—"} />
          <Stat label="Indexed sections" value={hydrated ? String(stats.sections) : "—"} />
        </div>

        {hydrated && loadError && (
          <UnavailableState
            title="Document service unavailable"
            detail="The authenticated tenant corpus could not be loaded. No local or bundled corpus was substituted."
          />
        )}

        {hydrated && !loadError && !corpusEnabled && (
          <UnavailableState
            title="Tenant document corpus disabled"
            detail="Document ingestion is not enabled for this deployment. Upload and report generation require the authenticated tenant corpus."
          />
        )}

        {corpusEnabled && (
          <>
            <SectionLabel>YOUR DOCUMENTS</SectionLabel>
            <div
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                void onFiles(event.dataTransfer.files);
              }}
              style={dropZone}
            >
              <div style={{ fontSize: 14, fontWeight: 600 }}>Upload a .md or .txt document</div>
              <div style={{ fontSize: 12.5, color: "var(--sub)", marginTop: 6, lineHeight: 1.5 }}>
                Markdown and plain text, up to {maxSizeLabel}, one file per upload. Drag and drop here, or{" "}
                <button onClick={() => fileRef.current?.click()} style={inlineLink}>browse files</button>.
              </div>
              {uploading && <Message>Uploading…</Message>}
              {uploadError && <Message error>{uploadError}</Message>}
              {uploadNotice && <Message>{uploadNotice}</Message>}
            </div>

            {hydrated && documents.length === 0 ? (
              <div style={emptyState}>
                No tenant documents yet. Upload a document to begin ingestion.
              </div>
            ) : (
              <div style={documentList}>
                {documents.map((doc, index) => {
                  const ingestion = doc.ingestion;
                  const processing = isProcessing(doc);
                  const failed = ingestion?.stage === "failed";
                  const awaitingFinalization =
                    ingestion?.stage === "ready" && ingestion.identity === "transitional";
                  return (
                    <div
                      key={doc.id}
                      style={{ ...documentRow, borderBottom: index < documents.length - 1 ? "1px solid var(--line)" : "none" }}
                    >
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                          <span style={{ fontSize: 14, fontWeight: 600 }}>{doc.title}</span>
                          {doc.type && <span style={kindBadge}>{doc.type}</span>}
                          <span style={failed ? failedBadge : processing ? processingBadge : statusBadge}>
                            {stageLabel(doc)}
                          </span>
                        </span>
                        <span style={metadataLine}>
                          {[
                            ingestion?.filename,
                            ingestion?.byteSize != null ? sizeLabel(ingestion.byteSize) : null,
                            doc.createdAt ? `uploaded ${formatDate(doc.createdAt)}` : null,
                            ingestion?.versionNo != null ? `v${ingestion.versionNo}` : null,
                            ingestion?.sectionCount != null ? `${ingestion.sectionCount} sections` : null,
                          ].filter(Boolean).join(" · ")}
                        </span>
                        {failed && ingestion?.errorMessage && (
                          <span style={{ display: "block", fontSize: 12, color: "#c34635", marginTop: 6 }}>
                            {ingestion.errorMessage}
                          </span>
                        )}
                      </span>
                      <span style={{ display: "flex", gap: 8, flex: "none", flexWrap: "wrap", justifyContent: "flex-end" }}>
                        {failed && <button onClick={() => void onRetry(doc.id)} style={ghostBtn}>Retry</button>}
                        {awaitingFinalization && <button onClick={() => void onFinalize(doc.id)} style={ghostBtn}>Finalize</button>}
                        {!processing && (
                          <button
                            onClick={() => {
                              versionTargetRef.current = doc.id;
                              versionFileRef.current?.click();
                            }}
                            style={ghostBtn}
                          >
                            New version
                          </button>
                        )}
                        <button onClick={() => void remove(doc.id)} style={ghostBtn}>Remove</button>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            <div style={noteBox}>
              <span style={{ fontFamily: mono, fontSize: 10.5, color: "var(--accent)", letterSpacing: ".08em", fontWeight: 600 }}>
                TENANT DOCUMENT INGESTION
              </span>
              <span style={{ fontSize: 13, color: "var(--ink2)" }}>
                Uploaded documents are stored for your organization and parsed into sections.
                {corpus?.generationEnabled
                  ? " Citation-ready current versions can be selected for report generation."
                  : " Tenant report generation is currently disabled."}
              </span>
            </div>
          </>
        )}
      </div>

      <style jsx global>{`
        @media (max-width: 760px) {
          .ev-stat-grid { grid-template-columns: repeat(2, 1fr) !important; }
        }
      `}</style>
    </AppShell>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div style={statCard}>
      <div style={{ fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".08em" }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 25, fontWeight: 700, marginTop: 7, color: accent ? "var(--accent)" : "var(--ink)" }}>{value}</div>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em", margin: "34px 0 14px" }}>{children}</div>;
}

function Message({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return <div style={{ fontSize: 12.5, color: error ? "#c34635" : "var(--accent)", marginTop: 8 }}>{children}</div>;
}

function UnavailableState({ title, detail }: { title: string; detail: string }) {
  return (
    <div style={unavailableState}>
      <div style={{ fontSize: 15, fontWeight: 700 }}>{title}</div>
      <div style={{ fontSize: 13, color: "var(--sub)", lineHeight: 1.55, marginTop: 6 }}>{detail}</div>
    </div>
  );
}

const headerBar: React.CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", height: 60, background: "var(--paper)", borderBottom: "1px solid var(--line)" };
const primaryBtn: React.CSSProperties = { fontFamily: "inherit", fontSize: 13, fontWeight: 600, color: "#fff", background: "#0a0a0b", border: "none", padding: "9px 16px", borderRadius: 8, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 };
const statGrid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 };
const statCard: React.CSSProperties = { background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 11, padding: "18px 20px" };
const unavailableState: React.CSSProperties = { padding: "24px", marginTop: 28, border: "1px solid var(--line2)", borderRadius: 12, background: "var(--panel)" };
const dropZone: React.CSSProperties = { padding: "24px", border: "1px dashed var(--line2)", borderRadius: 12, background: "var(--panel)", textAlign: "center" };
const inlineLink: React.CSSProperties = { border: "none", background: "transparent", color: "var(--accent)", font: "inherit", padding: 0, cursor: "pointer", textDecoration: "underline" };
const documentList: React.CSSProperties = { border: "1px solid var(--line)", borderRadius: 12, overflow: "hidden", background: "var(--panel)", marginTop: 14 };
const documentRow: React.CSSProperties = { display: "flex", alignItems: "center", gap: 20, padding: "18px 20px" };
const metadataLine: React.CSSProperties = { display: "block", fontFamily: mono, fontSize: 11, color: "var(--sub)", marginTop: 5 };
const kindBadge: React.CSSProperties = { fontFamily: mono, fontSize: 9.5, color: "var(--ink2)", border: "1px solid var(--line2)", borderRadius: 5, padding: "3px 7px" };
const statusBadge: React.CSSProperties = { fontFamily: mono, fontSize: 9.5, fontWeight: 600, color: "#207a4a", background: "rgba(32,122,74,.09)", borderRadius: 5, padding: "3px 7px" };
const processingBadge: React.CSSProperties = { ...statusBadge, color: "var(--accent)", background: "var(--accent-weak)" };
const failedBadge: React.CSSProperties = { ...statusBadge, color: "#c34635", background: "rgba(195,70,53,.09)" };
const ghostBtn: React.CSSProperties = { fontFamily: "inherit", fontSize: 12.5, fontWeight: 500, color: "var(--ink)", background: "var(--paper)", border: "1px solid var(--line2)", padding: "8px 12px", borderRadius: 8, cursor: "pointer" };
const emptyState: React.CSSProperties = { padding: "32px", marginTop: 14, textAlign: "center", fontSize: 13.5, color: "var(--sub)", border: "1px solid var(--line)", borderRadius: 12, background: "var(--panel)" };
const noteBox: React.CSSProperties = { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "12px 16px", border: "1px solid var(--line)", borderRadius: 10, background: "var(--accent-weak)", marginTop: 28 };
