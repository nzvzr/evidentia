"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { PLAYBOOK_TEMPLATES } from "@/lib/scenarios";
import { fetchBackendReports } from "@/lib/reportsApi";
import type { EvidentiaReport } from "@/lib/types";

const mono = "var(--font-plex-mono), monospace";

interface PlaybookCard {
  id: string;
  title: string;
  company: string;
  persona: string;
  market: string;
  generatedDate: string;
  confidence: number;
  risks: number;
  citations: number;
}

function toCard(r: EvidentiaReport): PlaybookCard {
  const d = new Date(r.generatedAt);
  const date = Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric", timeZone: "UTC" });
  return {
    id: r.id,
    title: `${r.persona} · ${r.market}`,
    company: r.company,
    persona: r.persona,
    market: r.market,
    generatedDate: date,
    confidence: r.confidence,
    risks: r.metrics.risksFlagged,
    citations: r.metrics.citationsUsed,
  };
}

export default function PlaybooksPage() {
  const router = useRouter();
  const [stored, setStored] = useState<EvidentiaReport[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    // Tenant reports come from the backend only — never from a browser cache.
    let cancelled = false;
    fetchBackendReports()
      .then((reports) => {
        if (!cancelled) setStored(reports);
      })
      .finally(() => {
        if (!cancelled) setHydrated(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const openReport = (rec: PlaybookCard) => router.push(`/reports/${rec.id}`);
  const openPrint = (rec: PlaybookCard) => window.open(`/playbook/${rec.id}/print`, "_blank");

  const recents: PlaybookCard[] = useMemo(() => stored.map(toCard), [stored]);

  return (
    <AppShell active="playbooks">
      {/* header */}
      <div style={headerBar}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <span style={{ fontWeight: 700, fontSize: 14.5 }}>Playbooks</span>
          <span style={{ color: "var(--line2)" }}>/</span>
          <span style={{ fontSize: 13.5, color: "var(--sub)" }}>Library</span>
        </div>
        <button onClick={() => router.push("/workspace")} style={primaryBtn}>
          <span style={{ fontSize: 15, lineHeight: 1, fontWeight: 400 }}>+</span> Create new playbook
        </button>
      </div>

      <div style={{ maxWidth: 1240, width: "100%", margin: "0 auto", padding: "32px 40px 64px" }}>
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>Playbooks</h1>
          <p style={{ fontSize: 14.5, color: "var(--sub)", margin: "9px 0 0", lineHeight: 1.5 }}>
            Exportable persona-specific reports generated from your documentation.
          </p>
        </div>

        {/* Tenant persistence note */}
        <div style={noteBox}>
          <span style={{ fontFamily: mono, fontSize: 10.5, color: "var(--accent)", letterSpacing: ".08em", fontWeight: 600 }}>
            TENANT LIBRARY
          </span>
          <span style={{ fontSize: 13, color: "var(--ink2)" }}>
            Generated reports are loaded from your organization&apos;s persisted workspace.
          </span>
        </div>

        {/* A. Recent playbooks */}
        <SectionLabel>RECENT PLAYBOOKS</SectionLabel>
        {hydrated && recents.length === 0 && (
          <div style={{ padding: "32px", textAlign: "center", color: "var(--sub)", border: "1px solid var(--line)", borderRadius: 12, background: "var(--panel)", marginBottom: 16 }}>
            No persisted playbooks yet. Generate a report from your tenant documents first.
          </div>
        )}
        <div style={cardGrid} className="ev-pb-grid">
          {recents.map((rec) => {
            return (
              <div key={rec.id} style={playbookCard}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: "-.01em" }}>{rec.title}</div>
                    <div style={{ fontSize: 12.5, color: "var(--sub)", marginTop: 4 }}>{rec.company}</div>
                  </div>
                  <StatusPill label="Ready" accent />
                </div>

                <div style={metaGrid}>
                  <Meta label="PERSONA" value={rec.persona} />
                  <Meta label="MARKET" value={rec.market} />
                  <Meta label="GENERATED" value={rec.generatedDate} monoValue />
                  <Meta label="CONFIDENCE" value={`${rec.confidence}%`} accent />
                </div>

                <div style={{ display: "flex", gap: 16, marginTop: 14, fontFamily: mono, fontSize: 11.5, color: "var(--sub)" }}>
                  <span>{rec.risks} risks</span>
                  <span>·</span>
                  <span>{rec.citations} citations</span>
                </div>

                <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
                  <button onClick={() => openReport(rec)} style={ghostBtn}>View report</button>
                  <button onClick={() => openPrint(rec)} style={darkBtn}>Export PDF</button>
                </div>
              </div>
            );
          })}
        </div>

        {/* B. Templates */}
        <SectionLabel top>PLAYBOOK TEMPLATES</SectionLabel>
        <div style={templateGrid} className="ev-tpl-grid">
          {PLAYBOOK_TEMPLATES.map((t) => (
            <div key={t.id} style={templateCard}>
              <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-.01em" }}>{t.name}</div>
              <p style={{ fontSize: 13, color: "var(--sub)", margin: "8px 0 0", lineHeight: 1.5 }}>{t.purpose}</p>
              <div style={{ marginTop: 16 }}>
                <div style={tplLabel}>BEST PERSONAS</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 7 }}>
                  {t.bestPersonas.map((p) => (
                    <span key={p} style={chip}>{p}</span>
                  ))}
                </div>
              </div>
              <div style={{ marginTop: 14 }}>
                <div style={tplLabel}>TYPICAL OUTPUTS</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 5, marginTop: 7 }}>
                  {t.outputs.map((o) => (
                    <div key={o} style={{ fontSize: 12.5, color: "var(--ink2)", display: "flex", gap: 8 }}>
                      <span style={{ color: "var(--accent)" }}>→</span>
                      {o}
                    </div>
                  ))}
                </div>
              </div>
              <button onClick={() => router.push("/workspace")} style={{ ...ghostBtn, marginTop: 18, width: "100%" }}>
                Use template
              </button>
            </div>
          ))}
        </div>
      </div>

      <style jsx global>{`
        @media (max-width: 1040px) {
          .ev-pb-grid {
            grid-template-columns: 1fr !important;
          }
          .ev-tpl-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }
        }
        @media (max-width: 680px) {
          .ev-tpl-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </AppShell>
  );
}

function SectionLabel({ children, top }: { children: React.ReactNode; top?: boolean }) {
  return (
    <div style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em", margin: top ? "40px 0 16px" : "0 0 16px" }}>
      {children}
    </div>
  );
}

function Meta({ label, value, accent, monoValue }: { label: string; value: string; accent?: boolean; monoValue?: boolean }) {
  return (
    <div>
      <div style={{ fontFamily: mono, fontSize: 9, color: "var(--sub)", letterSpacing: ".08em" }}>{label}</div>
      <div style={{ fontSize: monoValue ? 12 : 13, fontFamily: monoValue ? mono : undefined, fontWeight: 600, marginTop: 5, color: accent ? "var(--accent)" : "var(--ink)" }}>{value}</div>
    </div>
  );
}

function StatusPill({ label, accent }: { label: string; accent?: boolean }) {
  return (
    <span
      style={{
        fontFamily: mono,
        fontSize: 9.5,
        fontWeight: 600,
        letterSpacing: ".05em",
        padding: "4px 8px",
        borderRadius: 5,
        whiteSpace: "nowrap",
        color: accent ? "#fff" : "var(--ink2)",
        background: accent ? "var(--accent)" : "var(--shell)",
        border: accent ? "none" : "1px solid var(--line2)",
      }}
    >
      {label.toUpperCase()}
    </span>
  );
}

const headerBar: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
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

const noteBox: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  flexWrap: "wrap",
  padding: "12px 16px",
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--accent-weak)",
  marginBottom: 28,
};

const cardGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2,1fr)",
  gap: 16,
};

const playbookCard: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--line)",
  borderRadius: 12,
  padding: "22px 24px",
  display: "flex",
  flexDirection: "column",
};

const metaGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4,1fr)",
  gap: 12,
  marginTop: 18,
  paddingTop: 16,
  borderTop: "1px solid var(--line)",
};

const templateGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(3,1fr)",
  gap: 16,
};

const templateCard: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--line)",
  borderRadius: 12,
  padding: "22px 24px",
  display: "flex",
  flexDirection: "column",
};

const tplLabel: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 9.5,
  color: "var(--sub)",
  letterSpacing: ".08em",
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
  fontSize: 13,
  fontWeight: 500,
  color: "var(--ink)",
  background: "var(--paper)",
  border: "1px solid var(--line2)",
  padding: "9px 15px",
  borderRadius: 8,
  cursor: "pointer",
};

const darkBtn: React.CSSProperties = {
  fontFamily: "inherit",
  fontSize: 13,
  fontWeight: 600,
  color: "#fff",
  background: "#0a0a0b",
  border: "none",
  padding: "9px 16px",
  borderRadius: 8,
  cursor: "pointer",
};
