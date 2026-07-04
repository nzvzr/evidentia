"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import {
  CITATIONS,
  RISKS,
  AGENTS,
  deriveReport,
  DEFAULT_COMPANY,
} from "@/lib/demoReport";
import type { DerivedReport } from "@/lib/demoReport";
import { DEFAULT_SELECTION, readSelection } from "@/lib/useWorkspace";
import { recordFromReport, writeLastReport } from "@/lib/playbooksStore";

const mono = "var(--font-plex-mono), monospace";

export default function ReportPage() {
  const router = useRouter();
  const [report, setReport] = useState<DerivedReport>(() =>
    deriveReport(DEFAULT_SELECTION, DEFAULT_COMPANY),
  );
  const [chartReady, setChartReady] = useState(false);

  useEffect(() => {
    const sel = readSelection();
    const r = deriveReport(sel, DEFAULT_COMPANY);
    setReport(r);
    writeLastReport(recordFromReport(r, sel));
    const t = setTimeout(() => setChartReady(true), 160);
    return () => clearTimeout(t);
  }, []);

  const persona = report.persona;

  return (
    <AppShell active="reports">
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", height: 60, background: "var(--paper)", borderBottom: "1px solid var(--line)", position: "sticky", top: 0, zIndex: 5 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <span style={{ fontWeight: 700, fontSize: 14.5 }}>Report</span>
          <span style={{ color: "var(--line2)" }}>/</span>
          <span style={{ fontSize: 13.5, color: "var(--sub)" }}>{report.workspaceName}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button onClick={() => router.push("/workspace")} style={{ fontFamily: "inherit", fontSize: 13, fontWeight: 500, color: "var(--ink)", background: "var(--paper)", border: "1px solid var(--line2)", padding: "8px 15px", borderRadius: 8, cursor: "pointer" }}>
            New report
          </button>
          <button onClick={() => router.push("/playbook")} style={{ fontFamily: "inherit", fontSize: 13, fontWeight: 600, color: "#fff", background: "#0a0a0b", border: "none", padding: "9px 16px", borderRadius: 8, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 6, height: 6, borderRadius: 1, background: "var(--accent)" }} />
            Export playbook (PDF)
          </button>
        </div>
      </div>

      <div style={{ maxWidth: 1240, width: "100%", margin: "0 auto", padding: "32px 40px 64px" }}>
        {/* title block */}
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", gap: 16, marginBottom: 26 }}>
          <div>
            <div style={{ fontFamily: mono, fontSize: 11.5, color: "var(--accent)", letterSpacing: ".1em", textTransform: "uppercase" }}>
              Persona report · {report.marketLabel}
            </div>
            <h1 style={{ fontSize: 32, fontWeight: 700, letterSpacing: "-.02em", margin: "8px 0 0" }}>{report.personaTitle}</h1>
          </div>
          <div style={{ fontFamily: mono, fontSize: 11.5, color: "var(--sub)", textAlign: "right", lineHeight: 1.7 }}>
            <div>GENERATED {report.genStamp}</div>
            <div>7 AGENTS · {report.nDocs} DOCS · CONFIDENCE {report.confidence}%</div>
          </div>
        </div>

        {/* metric cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 1, background: "var(--line)", border: "1px solid var(--line)", borderRadius: 12, overflow: "hidden", marginBottom: 28 }} className="ev-metric-grid">
          {report.metrics.map((m) => (
            <div key={m.k} style={{ padding: "20px 20px", background: "var(--panel)" }}>
              <div style={{ fontFamily: mono, fontSize: 10.5, color: "var(--sub)", letterSpacing: ".06em", textTransform: "uppercase" }}>{m.k}</div>
              <div style={{ fontSize: 27, fontWeight: 700, letterSpacing: "-.02em", marginTop: 9, color: m.accent ? "var(--accent)" : "var(--ink)" }}>{m.v}</div>
              <div style={{ fontSize: 11.5, color: "var(--sub)", marginTop: 4 }}>{m.s}</div>
            </div>
          ))}
        </div>

        {/* executive summary */}
        <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, padding: "22px 26px", marginBottom: 28 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em" }}>EXECUTIVE SUMMARY</span>
            <span style={{ flex: 1, height: 1, background: "var(--line)" }} />
          </div>
          <p style={{ fontSize: 15, lineHeight: 1.62, color: "var(--ink2)", margin: 0 }}>{report.execSummary}</p>
        </div>

        {/* two-column body */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 28, alignItems: "start" }} className="ev-report-grid">
          {/* LEFT */}
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            {/* persona brief */}
            <Card>
              <SectionLabel>PERSONA BRIEF</SectionLabel>
              <p style={{ fontSize: 16, lineHeight: 1.62, color: "var(--ink2)", margin: 0 }}>{persona.brief}</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 20 }}>
                {persona.priorities.map((p) => (
                  <span key={p} style={{ fontFamily: mono, fontSize: 11, color: "var(--ink)", background: "var(--shell)", border: "1px solid var(--line)", padding: "6px 11px", borderRadius: 6 }}>{p}</span>
                ))}
              </div>
            </Card>

            {/* workflow steps */}
            <Card>
              <SectionLabel>RECOMMENDED WORKFLOW</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {persona.steps.map((s, i) => (
                  <div key={s.t} style={{ display: "flex", gap: 15, alignItems: "flex-start", padding: "15px 0", borderBottom: i < persona.steps.length - 1 ? "1px solid var(--line)" : "none" }}>
                    <div style={{ width: 26, height: 26, flex: "none", borderRadius: "50%", border: "1px solid var(--line2)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: mono, fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>
                      {String(i + 1).padStart(2, "0")}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14.5, fontWeight: 600, color: "var(--ink)" }}>{s.t}</div>
                      <div style={{ fontSize: 13, color: "var(--sub)", marginTop: 3, lineHeight: 1.5 }}>{s.d}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            {/* risks */}
            <Card>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em" }}>RISKS &amp; WARNINGS</span>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{RISKS.length} flagged</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {RISKS.map((r) => {
                  const high = r.sev === "HIGH";
                  return (
                    <div key={r.title} style={{ display: "flex", gap: 14, padding: "15px 16px", border: "1px solid var(--line)", borderRadius: 10, background: "var(--shell)" }}>
                      <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, letterSpacing: ".05em", padding: "4px 8px", borderRadius: 5, height: "fit-content", flex: "none", color: high ? "#fff" : "var(--ink)", background: high ? "var(--accent)" : "transparent", border: high ? "none" : "1px solid var(--line2)" }}>
                        {r.sev}
                      </span>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{r.title}</div>
                        <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 4, lineHeight: 1.5 }}>{r.detail}</div>
                        <div style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", marginTop: 7 }}>{r.src}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          </div>

          {/* RIGHT */}
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            {/* agent timeline */}
            <Card pad="24px 24px">
              <SectionLabel>AGENT TIMELINE</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {AGENTS.map((t) => (
                  <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 0" }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--accent)", flex: "none" }} />
                    <span style={{ fontSize: 13, color: "var(--ink)", flex: 1 }}>{t.name}</span>
                    <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{t.dur}</span>
                  </div>
                ))}
              </div>
            </Card>

            {/* document relevance */}
            <Card pad="24px 24px">
              <SectionLabel>DOCUMENT RELEVANCE</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 15 }}>
                {report.relevance.map((d) => (
                  <div key={d.id}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                      <span style={{ fontSize: 12.5, color: "var(--ink)" }}>{d.short}</span>
                      <span style={{ fontFamily: mono, fontSize: 11.5, color: "var(--sub)" }}>{d.pct}%</span>
                    </div>
                    <div style={{ height: 7, background: "var(--shell)", borderRadius: 4, overflow: "hidden" }}>
                      <div style={{ width: `${chartReady ? d.pct : 0}%`, height: "100%", background: d.pct >= 85 ? "var(--accent)" : "#0a0a0b", borderRadius: 4, transition: "width .8s cubic-bezier(.22,1,.36,1)" }} />
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            {/* citations */}
            <Card pad="24px 24px">
              <SectionLabel>CITATIONS</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {CITATIONS.map((c, i) => (
                  <div key={c.tag} style={{ display: "flex", gap: 12, padding: "13px 0", borderBottom: i < CITATIONS.length - 1 ? "1px solid var(--line)" : "none" }}>
                    <span style={{ fontFamily: mono, fontSize: 10.5, fontWeight: 600, color: "#fff", background: "#0a0a0b", padding: "3px 7px", borderRadius: 5, flex: "none", alignSelf: "flex-start", whiteSpace: "nowrap" }}>{c.tag}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink)" }}>{c.doc}</div>
                      <div style={{ fontSize: 12.5, color: "var(--ink2)", marginTop: 4, lineHeight: 1.5, fontStyle: "italic" }}>&ldquo;{c.snippet}&rdquo;</div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            {/* suggested actions */}
            <div style={{ background: "#0a0a0b", color: "#f5f5f3", borderRadius: 12, padding: "24px 24px" }}>
              <div style={{ fontFamily: mono, fontSize: 11, color: "rgba(245,245,243,.5)", letterSpacing: ".08em", marginBottom: 18 }}>SUGGESTED ACTIONS</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                {persona.actions.map((a) => (
                  <div key={a.title} style={{ display: "flex", gap: 13, alignItems: "flex-start", padding: "13px 14px", border: "1px solid rgba(255,255,255,.12)", borderRadius: 9 }}>
                    <span style={{ color: "var(--accent)", fontFamily: mono, fontSize: 13, fontWeight: 600, lineHeight: 1.3 }}>→</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{a.title}</div>
                      <div style={{ fontSize: 12.5, color: "rgba(245,245,243,.55)", marginTop: 3, lineHeight: 1.45 }}>{a.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
              <button onClick={() => router.push("/playbook")} style={{ width: "100%", marginTop: 18, fontFamily: "inherit", fontSize: 13.5, fontWeight: 600, color: "#0a0a0b", background: "#fff", border: "none", padding: 12, borderRadius: 9, cursor: "pointer" }}>
                Export full playbook →
              </button>
            </div>
          </div>
        </div>
      </div>

      <style jsx global>{`
        @media (max-width: 1040px) {
          .ev-report-grid {
            grid-template-columns: 1fr !important;
          }
        }
        @media (max-width: 760px) {
          .ev-metric-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }
        }
      `}</style>
    </AppShell>
  );
}

function Card({ children, pad = "26px 28px" }: { children: React.ReactNode; pad?: string }) {
  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, padding: pad }}>
      {children}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em", marginBottom: 16 }}>
      {children}
    </div>
  );
}
