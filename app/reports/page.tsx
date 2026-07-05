"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { DEMO_REPORTS } from "@/data/demoReports";
import { REPORT_CATEGORIES } from "@/lib/scenarios";
import { getReports } from "@/lib/reportsStore";
import type { EvidentiaReport } from "@/lib/types";

const mono = "var(--font-plex-mono), monospace";

interface Card {
  id: string;
  title: string;
  company: string;
  persona: string;
  market: string;
  generatedDate: string;
  confidence: number;
  documents: number;
  citations: number;
  risks: number;
  status: string;
  category: string;
  isLocal: boolean;
}

function toCard(r: EvidentiaReport, isLocal: boolean): Card {
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
    documents: r.metrics.documentsAnalyzed,
    citations: r.metrics.citationsUsed,
    risks: r.metrics.risksFlagged,
    status: isLocal ? "This session" : "Ready",
    category: r.category,
    isLocal,
  };
}

export default function ReportsPage() {
  const router = useRouter();
  const [stored, setStored] = useState<EvidentiaReport[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("All");

  useEffect(() => {
    setStored(getReports());
  }, []);

  const cards: Card[] = useMemo(() => {
    const localCards = stored.map((r) => toCard(r, true));
    const localIds = new Set(localCards.map((c) => c.id));
    const demoCards = DEMO_REPORTS.filter((r) => !localIds.has(r.id)).map((r) => toCard(r, false));
    return [...localCards, ...demoCards];
  }, [stored]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return cards.filter((c) => {
      const inCat = category === "All" || c.category === category;
      const inQuery =
        !q || [c.title, c.persona, c.market, c.company].some((f) => f.toLowerCase().includes(q));
      return inCat && inQuery;
    });
  }, [cards, query, category]);

  return (
    <AppShell active="reports">
      <div style={headerBar}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <span style={{ fontWeight: 700, fontSize: 14.5 }}>Reports</span>
          <span style={{ color: "var(--line2)" }}>/</span>
          <span style={{ fontSize: 13.5, color: "var(--sub)" }}>Library</span>
        </div>
        <button onClick={() => router.push("/workspace")} style={primaryBtn}>
          <span style={{ fontSize: 15, lineHeight: 1, fontWeight: 400 }}>+</span> New workspace
        </button>
      </div>

      <div style={{ maxWidth: 1240, width: "100%", margin: "0 auto", padding: "32px 40px 64px" }}>
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>Reports</h1>
          <p style={{ fontSize: 14.5, color: "var(--sub)", margin: "9px 0 0", lineHeight: 1.5 }}>
            Generated persona reports and evidence-backed playbooks.
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 22 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {REPORT_CATEGORIES.map((c) => {
              const on = c === category;
              return (
                <button
                  key={c}
                  onClick={() => setCategory(c)}
                  style={{
                    fontFamily: "inherit",
                    fontSize: 12.5,
                    fontWeight: on ? 600 : 500,
                    cursor: "pointer",
                    padding: "7px 14px",
                    borderRadius: 8,
                    color: on ? "#fff" : "var(--ink)",
                    background: on ? "#0a0a0b" : "var(--paper)",
                    border: `1px solid ${on ? "#0a0a0b" : "var(--line2)"}`,
                  }}
                >
                  {c}
                </button>
              );
            })}
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search reports…"
            style={{ width: 240, maxWidth: "100%", fontFamily: "inherit", fontSize: 13.5, color: "var(--ink)", background: "var(--paper)", border: "1px solid var(--line2)", borderRadius: 9, padding: "10px 13px", outline: "none" }}
          />
        </div>

        {filtered.length === 0 ? (
          <div style={{ padding: "48px 0", textAlign: "center", color: "var(--sub)", fontSize: 14 }}>
            No reports match your search.
          </div>
        ) : (
          <div style={cardGrid} className="ev-rep-grid">
            {filtered.map((rec) => (
              <div key={rec.id} style={reportCard}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: "-.01em" }}>{rec.title}</div>
                    <div style={{ fontSize: 12.5, color: "var(--sub)", marginTop: 4 }}>{rec.company}</div>
                  </div>
                  <StatusPill label={rec.status} accent={rec.isLocal} />
                </div>

                <div style={metaGrid}>
                  <Meta label="PERSONA" value={rec.persona} />
                  <Meta label="MARKET" value={rec.market} />
                  <Meta label="GENERATED" value={rec.generatedDate} monoValue />
                  <Meta label="CONFIDENCE" value={`${rec.confidence}%`} accent />
                </div>

                <div style={{ display: "flex", gap: 14, marginTop: 14, fontFamily: mono, fontSize: 11.5, color: "var(--sub)" }}>
                  <span>{rec.documents} docs</span>
                  <span>·</span>
                  <span>{rec.citations} citations</span>
                  <span>·</span>
                  <span>{rec.risks} risks</span>
                </div>

                <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
                  <button onClick={() => router.push(`/reports/${rec.id}`)} style={ghostBtn}>View report</button>
                  <button onClick={() => window.open(`/playbook/${rec.id}/print`, "_blank")} style={darkBtn}>Export playbook</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <style jsx global>{`
        @media (max-width: 1040px) {
          .ev-rep-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </AppShell>
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

const cardGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2,1fr)",
  gap: 16,
};

const reportCard: React.CSSProperties = {
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
