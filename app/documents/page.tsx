"use client";

import { useMemo, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import { DEMO_DOCS } from "@/lib/demoDocs";
import { RISKS } from "@/lib/demoReport";
import { PERSONAS } from "@/lib/personas";
import { useUploads } from "@/lib/uploads";
import type { DemoDoc, UploadedDoc } from "@/lib/types";

const mono = "var(--font-plex-mono), monospace";

interface DocDetail {
  title: string;
  kind: string;
  category: string;
  description: string;
  citationIds: string[];
  excerpt: string;
  personas: string[];
  topics: string[];
  relatedRisks: { title: string; sev: string }[];
}

function fromDemo(doc: DemoDoc): DocDetail {
  const relatedRisks = RISKS.filter((r) => doc.citationIds.includes(r.ref)).map((r) => ({
    title: r.title,
    sev: r.sev,
  }));
  return {
    title: doc.name,
    kind: doc.kind,
    category: doc.category,
    description: doc.description,
    citationIds: doc.citationIds,
    excerpt: doc.sampleExcerpt,
    personas: doc.usedByPersonas,
    topics: doc.topics,
    relatedRisks,
  };
}

function fromUpload(doc: UploadedDoc): DocDetail {
  return {
    title: doc.name,
    kind: doc.kind,
    category: doc.category,
    description: "Session upload processed locally in your browser.",
    citationIds: [],
    excerpt: doc.excerpt,
    personas: [],
    topics: [],
    relatedRisks: [],
  };
}

export default function DocumentsPage() {
  const { uploads, hydrated, addFile, remove } = useUploads();
  const [detail, setDetail] = useState<DocDetail | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const stats = useMemo(() => {
    const anchors = DEMO_DOCS.reduce((a, d) => a + d.citationIds.length, 0);
    return {
      indexed: DEMO_DOCS.length,
      passages: "1,284",
      anchors,
      personas: PERSONAS.length,
      uploads: uploads.length,
    };
  }, [uploads.length]);

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadError(null);
    for (const file of Array.from(files)) {
      if (!/\.(txt|md)$/i.test(file.name)) {
        setUploadError("Only .txt and .md files are supported in demo mode.");
        continue;
      }
      await addFile(file);
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <AppShell active="documents">
      {/* header */}
      <div style={headerBar}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <span style={{ fontWeight: 700, fontSize: 14.5 }}>Documents</span>
          <span style={{ color: "var(--line2)" }}>/</span>
          <span style={{ fontSize: 13.5, color: "var(--sub)" }}>Corpus</span>
        </div>
        <button onClick={() => fileRef.current?.click()} style={primaryBtn}>
          <span style={{ fontSize: 15, lineHeight: 1, fontWeight: 400 }}>+</span> Upload documents
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.md,text/plain,text/markdown"
          multiple
          onChange={(e) => onFiles(e.target.files)}
          style={{ display: "none" }}
        />
      </div>

      <div style={{ maxWidth: 1240, width: "100%", margin: "0 auto", padding: "32px 40px 64px" }}>
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>Documents</h1>
          <p style={{ fontSize: 14.5, color: "var(--sub)", margin: "9px 0 0", lineHeight: 1.5 }}>
            Manage the corpus Evidentia uses to generate evidence-backed playbooks.
          </p>
        </div>

        {/* D. Corpus stats */}
        <div style={statGrid} className="ev-stat-grid">
          <Stat k="Documents indexed" v={String(stats.indexed)} />
          <Stat k="Passages available" v={stats.passages} />
          <Stat k="Citation anchors" v={String(stats.anchors)} />
          <Stat k="Personas supported" v={String(stats.personas)} />
          <Stat k="Session uploads" v={hydrated ? String(stats.uploads) : "—"} accent />
        </div>

        {/* A. Demo corpus */}
        <SectionLabel top>DEMO CORPUS</SectionLabel>
        <div style={{ border: "1px solid var(--line)", borderRadius: 12, overflow: "hidden", background: "var(--panel)" }}>
          {DEMO_DOCS.map((doc, i) => (
            <button
              key={doc.id}
              onClick={() => setDetail(fromDemo(doc))}
              style={{ ...docRow, borderBottom: i < DEMO_DOCS.length - 1 ? "1px solid var(--line)" : "none" }}
            >
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{doc.name}</span>
                  <span style={kindBadge}>{doc.kind}</span>
                  <span style={statusBadge}>{doc.status}</span>
                </span>
                <span style={{ display: "block", fontFamily: mono, fontSize: 11, color: "var(--sub)", marginTop: 5 }}>
                  {doc.category} · {doc.pages} · updated {doc.updatedAt}
                </span>
                <span style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                  {doc.citationIds.map((c) => (
                    <span key={c} style={citeTag}>{c}</span>
                  ))}
                </span>
              </span>
              <span style={{ flex: "none", textAlign: "right", maxWidth: 220 }} className="ev-doc-used">
                <span style={{ fontFamily: mono, fontSize: 9, color: "var(--sub)", letterSpacing: ".08em" }}>USED BY</span>
                <span style={{ display: "block", fontSize: 12, color: "var(--ink2)", marginTop: 4, lineHeight: 1.4 }}>
                  {doc.usedByPersonas.join(", ")}
                </span>
              </span>
            </button>
          ))}
        </div>

        {/* B. Session uploads */}
        <SectionLabel top>SESSION UPLOADS</SectionLabel>
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            onFiles(e.dataTransfer.files);
          }}
          style={dropZone}
        >
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>Upload .txt or .md documents</div>
          <div style={{ fontSize: 12.5, color: "var(--sub)", marginTop: 6, lineHeight: 1.5 }}>
            Drag &amp; drop here, or{" "}
            <button onClick={() => fileRef.current?.click()} style={inlineLink}>browse files</button>. Processed locally — never uploaded.
          </div>
          {uploadError && (
            <div style={{ fontSize: 12.5, color: "var(--risk, #c34635)", marginTop: 8 }}>{uploadError}</div>
          )}
        </div>

        {hydrated && uploads.length > 0 && (
          <div style={{ border: "1px solid var(--line)", borderRadius: 12, overflow: "hidden", background: "var(--panel)", marginTop: 14 }}>
            {uploads.map((doc, i) => (
              <div key={doc.id} style={{ ...docRow, cursor: "default", borderBottom: i < uploads.length - 1 ? "1px solid var(--line)" : "none" }}>
                <button onClick={() => setDetail(fromUpload(doc))} style={{ flex: 1, minWidth: 0, textAlign: "left", background: "transparent", border: "none", font: "inherit", cursor: "pointer", padding: 0 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{doc.name}</span>
                    <span style={kindBadge}>{doc.kind}</span>
                    <span style={statusBadge}>{doc.status}</span>
                  </span>
                  <span style={{ display: "block", fontFamily: mono, fontSize: 11, color: "var(--sub)", marginTop: 5 }}>
                    {doc.filename} · {doc.sizeLabel} · {doc.uploadedAt}
                  </span>
                </button>
                <button onClick={() => remove(doc.id)} style={ghostBtn}>Remove</button>
              </div>
            ))}
          </div>
        )}

        <div style={noteBox}>
          <span style={{ fontFamily: mono, fontSize: 10.5, color: "var(--accent)", letterSpacing: ".08em", fontWeight: 600 }}>DEMO MODE</span>
          <span style={{ fontSize: 13, color: "var(--ink2)" }}>
            Uploaded documents are processed locally for this session and are not permanently stored.
          </span>
        </div>
      </div>

      {/* C. Details drawer */}
      {detail && <DetailDrawer detail={detail} onClose={() => setDetail(null)} />}

      <style jsx global>{`
        @media (max-width: 760px) {
          .ev-stat-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }
          .ev-doc-used {
            display: none !important;
          }
        }
      `}</style>
    </AppShell>
  );
}

function DetailDrawer({ detail, onClose }: { detail: DocDetail; onClose: () => void }) {
  return (
    <div className="no-print" onClick={onClose} style={drawerOverlay} role="dialog" aria-modal="true">
      <aside onClick={(e) => e.stopPropagation()} style={drawerPanel} className="ev-in">
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={kindBadge}>{detail.kind}</span>
              <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{detail.category}</span>
            </div>
            <h2 style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-.02em", margin: "12px 0 0" }}>{detail.title}</h2>
          </div>
          <button onClick={onClose} style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: 20, color: "var(--sub)", lineHeight: 1 }}>×</button>
        </div>

        <p style={{ fontSize: 13.5, color: "var(--ink2)", lineHeight: 1.55, margin: "18px 0 0" }}>{detail.description}</p>

        {detail.citationIds.length > 0 && (
          <DrawerBlock label="CITATION IDS">
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {detail.citationIds.map((c) => (
                <span key={c} style={citeTag}>{c}</span>
              ))}
            </div>
          </DrawerBlock>
        )}

        <DrawerBlock label="SAMPLE EXCERPT">
          <div style={{ fontSize: 13, color: "var(--ink2)", lineHeight: 1.6, fontStyle: "italic", padding: "12px 14px", background: "var(--shell)", border: "1px solid var(--line)", borderRadius: 9 }}>
            &ldquo;{detail.excerpt}&rdquo;
          </div>
        </DrawerBlock>

        {detail.personas.length > 0 && (
          <DrawerBlock label="RECOMMENDED PERSONAS">
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {detail.personas.map((p) => (
                <span key={p} style={chip}>{p}</span>
              ))}
            </div>
          </DrawerBlock>
        )}

        {detail.topics.length > 0 && (
          <DrawerBlock label="TOPICS COVERED">
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {detail.topics.map((t) => (
                <span key={t} style={chip}>{t}</span>
              ))}
            </div>
          </DrawerBlock>
        )}

        {detail.relatedRisks.length > 0 && (
          <DrawerBlock label="RELATED RISKS">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {detail.relatedRisks.map((r) => (
                <div key={r.title} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                  <span style={{ fontFamily: mono, fontSize: 9.5, fontWeight: 600, color: r.sev === "HIGH" ? "#fff" : "var(--ink)", background: r.sev === "HIGH" ? "#c34635" : "transparent", border: r.sev === "HIGH" ? "none" : "1px solid var(--line2)", padding: "3px 7px", borderRadius: 5, flex: "none" }}>{r.sev}</span>
                  <span style={{ fontSize: 12.5, color: "var(--ink2)", lineHeight: 1.4 }}>{r.title}</span>
                </div>
              ))}
            </div>
          </DrawerBlock>
        )}
      </aside>
    </div>
  );
}

function DrawerBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 20 }}>
      <div style={{ fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".08em", marginBottom: 9 }}>{label}</div>
      {children}
    </div>
  );
}

function Stat({ k, v, accent }: { k: string; v: string; accent?: boolean }) {
  return (
    <div style={{ padding: "18px 20px", background: "var(--panel)" }}>
      <div style={{ fontFamily: mono, fontSize: 10, color: "var(--sub)", letterSpacing: ".06em", textTransform: "uppercase" }}>{k}</div>
      <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-.02em", marginTop: 8, color: accent ? "var(--accent)" : "var(--ink)" }}>{v}</div>
    </div>
  );
}

function SectionLabel({ children, top }: { children: React.ReactNode; top?: boolean }) {
  return (
    <div style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em", margin: top ? "40px 0 16px" : "0 0 16px" }}>
      {children}
    </div>
  );
}

const headerBar: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
  padding: "0 28px",
  height: 60,
  background: "var(--paper)",
  borderBottom: "1px solid var(--line)",
};

const primaryBtn: React.CSSProperties = {
  fontFamily: "inherit",
  fontSize: 13,
  fontWeight: 600,
  color: "#fff",
  background: "#0a0a0b",
  border: "none",
  padding: "9px 16px",
  borderRadius: 8,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const statGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(5,1fr)",
  gap: 1,
  background: "var(--line)",
  border: "1px solid var(--line)",
  borderRadius: 12,
  overflow: "hidden",
};

const docRow: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 16,
  padding: "16px 18px",
  width: "100%",
  textAlign: "left",
  font: "inherit",
  background: "var(--paper)",
  border: "none",
  cursor: "pointer",
};

const kindBadge: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 10,
  color: "var(--sub)",
  padding: "3px 7px",
  border: "1px solid var(--line2)",
  borderRadius: 5,
};

const statusBadge: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 9.5,
  fontWeight: 600,
  letterSpacing: ".04em",
  color: "var(--accent)",
  background: "var(--accent-weak)",
  padding: "3px 8px",
  borderRadius: 5,
};

const citeTag: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 10,
  fontWeight: 600,
  color: "#fff",
  background: "#0a0a0b",
  padding: "3px 7px",
  borderRadius: 5,
  whiteSpace: "nowrap",
};

const chip: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 11,
  color: "var(--ink)",
  background: "var(--shell)",
  border: "1px solid var(--line)",
  padding: "4px 9px",
  borderRadius: 6,
};

const ghostBtn: React.CSSProperties = {
  fontFamily: "inherit",
  fontSize: 12.5,
  fontWeight: 500,
  color: "var(--ink)",
  background: "var(--paper)",
  border: "1px solid var(--line2)",
  padding: "7px 13px",
  borderRadius: 8,
  cursor: "pointer",
  flex: "none",
};

const dropZone: React.CSSProperties = {
  border: "1.5px dashed var(--line2)",
  borderRadius: 12,
  padding: "24px 22px",
  background: "var(--panel)",
  textAlign: "center",
};

const inlineLink: React.CSSProperties = {
  fontFamily: "inherit",
  fontSize: 12.5,
  fontWeight: 600,
  color: "var(--accent)",
  background: "none",
  border: "none",
  cursor: "pointer",
  padding: 0,
};

const noteBox: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  flexWrap: "wrap",
  padding: "12px 16px",
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--accent-weak)",
  marginTop: 24,
};

const drawerOverlay: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 100,
  background: "rgba(10,10,11,.45)",
  display: "flex",
  justifyContent: "flex-end",
};

const drawerPanel: React.CSSProperties = {
  width: 420,
  maxWidth: "100%",
  height: "100vh",
  overflowY: "auto",
  background: "#fff",
  borderLeft: "1px solid var(--line)",
  padding: "26px 28px",
  boxShadow: "-24px 0 70px rgba(0,0,0,.2)",
};
