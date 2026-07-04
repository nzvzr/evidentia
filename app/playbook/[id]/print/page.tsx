"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Logo from "@/components/Logo";
import {
  CITATIONS,
  RISKS,
  DEFAULT_COMPANY,
  SEVERITY_COLORS,
  WORKFLOW_CITE_TAGS,
  deriveReport,
  derivePlaybookInsights,
  severityCounts,
} from "@/lib/demoReport";
import type { DerivedReport, PlaybookInsights } from "@/lib/demoReport";
import type { Severity, WorkspaceSelection } from "@/lib/types";
import { getReportById } from "@/lib/scenarios";
import { DEFAULT_SELECTION, readSelection } from "@/lib/useWorkspace";

const mono = "var(--font-plex-mono), monospace";
const TOTAL_PAGES = 6;

/** Deterministic selection for first render (no localStorage → no hydration mismatch). */
function staticSelectionForId(id: string): WorkspaceSelection {
  if (id === "current") return DEFAULT_SELECTION;
  return getReportById(id)?.selection ?? DEFAULT_SELECTION;
}

/** Resolved selection incl. localStorage — used after mount. */
function selectionForId(id: string): WorkspaceSelection {
  if (id === "current") return readSelection();
  return getReportById(id)?.selection ?? readSelection();
}

export default function PrintPlaybookPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = (Array.isArray(params.id) ? params.id[0] : params.id) || "current";

  const [report, setReport] = useState<DerivedReport>(() =>
    deriveReport(staticSelectionForId(id), DEFAULT_COMPANY),
  );
  const [insights, setInsights] = useState<PlaybookInsights>(() => {
    const s = staticSelectionForId(id);
    return derivePlaybookInsights(s, deriveReport(s, DEFAULT_COMPANY));
  });

  useEffect(() => {
    const sel = selectionForId(id);
    const r = deriveReport(sel, DEFAULT_COMPANY);
    setReport(r);
    setInsights(derivePlaybookInsights(sel, r));
    try {
      window.scrollTo(0, 0);
    } catch {
      /* ignore */
    }
  }, [id]);

  const persona = report.persona;
  const counts = severityCounts();
  const totalRisks = RISKS.length || 1;

  return (
    <div style={{ minHeight: "100vh", background: "#d7d7d3" }}>
      {/* toolbar (hidden on print) */}
      <div className="no-print" style={{ position: "sticky", top: 0, zIndex: 10, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", height: 56, background: "var(--paper)", borderBottom: "1px solid var(--line)" }}>
        <button onClick={() => router.push(`/reports/${id}`)} style={{ fontFamily: "inherit", fontSize: 13, fontWeight: 500, color: "var(--ink)", background: "transparent", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
          ← Back to report
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>EXPORT PREVIEW · 6-PAGE REPORT</span>
          <button onClick={() => window.print()} style={{ fontFamily: "inherit", fontSize: 13, fontWeight: 600, color: "#fff", background: "#0a0a0b", border: "none", padding: "9px 16px", borderRadius: 8, cursor: "pointer" }}>
            Print / Save as PDF
          </button>
        </div>
      </div>

      <div className="print-shell">
        {/* ===== PAGE 1 · COVER / EXECUTIVE SUMMARY ===== */}
        <section className="print-page">
          <div className="page-content">
            <PageHeader confidential report={report} showMeta={false} />
            <div style={{ marginTop: 44 }}>
              <div style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", letterSpacing: ".16em", textTransform: "uppercase" }}>Persona Playbook</div>
              <h1 style={{ fontSize: 48, fontWeight: 700, letterSpacing: "-.03em", lineHeight: 1, margin: "14px 0 0" }}>{report.personaTitle}</h1>
              <div style={{ fontSize: 15, color: "var(--sub)", marginTop: 12 }}>{report.company} — {report.marketLabel} market</div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", border: "1px solid var(--line2)", borderRadius: 9, overflow: "hidden", marginTop: 30 }}>
              <MetaCell label="COMPANY" value={report.company} />
              <MetaCell label="MARKET" value={report.marketLabel} />
              <MetaCell label="PERSONA" value={report.personaTitle} />
              <MetaCell label="GENERATED" value={report.genStamp} mono />
              <div style={{ padding: "15px 16px" }}>
                <div style={metaLabel}>CONFIDENCE</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: "var(--accent)", marginTop: 3, letterSpacing: "-.02em" }}>{report.confidence}%</div>
              </div>
            </div>

            <div style={{ marginTop: 36 }}>
              <SectionTitle>01 · EXECUTIVE SUMMARY</SectionTitle>
              <p style={{ fontSize: 14.5, lineHeight: 1.7, color: "var(--ink2)", margin: 0 }}>{report.execSummary}</p>
            </div>

            <div style={{ marginTop: 22, padding: "16px 18px", border: "1px solid var(--line2)", borderRadius: 9, background: "var(--accent-weak)" }}>
              <div style={{ fontFamily: mono, fontSize: 9.5, color: "var(--accent)", letterSpacing: ".1em", fontWeight: 600 }}>TOP FINDING</div>
              <div style={{ fontSize: 14.5, fontWeight: 600, color: "var(--ink)", marginTop: 7, lineHeight: 1.5 }}>{report.topFinding}</div>
              <div style={{ fontSize: 12.5, color: "var(--sub)", marginTop: 6, lineHeight: 1.5 }}>Business impact: {RISKS[0].impact}</div>
            </div>

            <div style={{ marginTop: 32 }}>
              <SectionTitle>02 · TOP RECOMMENDATIONS</SectionTitle>
              {persona.actions.slice(0, 3).map((a, i) => (
                <div key={a.title} style={{ display: "flex", gap: 16, padding: "15px 0", borderBottom: i < 2 ? "1px solid var(--line)" : "none" }}>
                  <span style={{ fontFamily: mono, fontSize: 13, fontWeight: 600, color: "var(--accent)" }}>{String(i + 1).padStart(2, "0")}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14.5, fontWeight: 600, color: "var(--ink)" }}>{a.title}</div>
                    <div style={{ fontSize: 13, color: "var(--sub)", marginTop: 3, lineHeight: 1.5 }}>{a.detail}</div>
                  </div>
                </div>
              ))}
            </div>

            <PageFooter report={report} page={1} />
          </div>
        </section>

        {/* ===== PAGE 2 · INSIGHT DASHBOARD ===== */}
        <section className="print-page">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={22}>INSIGHT DASHBOARD</SectionTitle>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", border: "1px solid var(--line2)", borderRadius: 9, overflow: "hidden", marginBottom: 22 }}>
                {report.metrics.map((m) => (
                  <div key={m.k} style={{ padding: "14px 14px", borderRight: "1px solid var(--line)" }}>
                    <div style={metaLabel}>{m.k.toUpperCase()}</div>
                    <div style={{ fontSize: 20, fontWeight: 700, marginTop: 6, letterSpacing: "-.02em", color: m.accent ? "var(--accent)" : "var(--ink)" }}>{m.v}</div>
                  </div>
                ))}
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, gridAutoRows: "1fr" }}>
                <InsightCard title="Document Relevance">
                  <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
                    {report.relevance.map((d) => (
                      <div key={d.id}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                          <span style={{ fontSize: 12, color: "var(--ink)" }}>{d.short}</span>
                          <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{d.pct}%</span>
                        </div>
                        <Bar pct={d.pct} />
                      </div>
                    ))}
                  </div>
                </InsightCard>

                <InsightCard title="Risk Severity Breakdown">
                  <div style={{ height: 14, borderRadius: 4, overflow: "hidden", display: "flex" }}>
                    <div style={{ width: `${(counts.HIGH / totalRisks) * 100}%`, background: SEVERITY_COLORS.HIGH }} />
                    <div style={{ width: `${(counts.MED / totalRisks) * 100}%`, background: SEVERITY_COLORS.MED }} />
                    <div style={{ width: `${(counts.LOW / totalRisks) * 100}%`, background: SEVERITY_COLORS.LOW }} />
                  </div>
                  <div style={{ display: "flex", gap: 20, marginTop: 18 }}>
                    {([["High", counts.HIGH, SEVERITY_COLORS.HIGH], ["Medium", counts.MED, SEVERITY_COLORS.MED], ["Low", counts.LOW, SEVERITY_COLORS.LOW]] as const).map(([label, count, color]) => (
                      <div key={label} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                        <span style={{ width: 9, height: 9, borderRadius: 2, background: color }} />
                        <span style={{ fontSize: 12, color: "var(--ink)" }}>{label}</span>
                        <span style={{ fontFamily: mono, fontSize: 12, fontWeight: 600, color: "var(--sub)" }}>{count}</span>
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: 11.5, color: "var(--sub)", marginTop: "auto", paddingTop: 16, lineHeight: 1.5 }}>
                    {totalRisks} risks flagged across the analyzed corpus, weighted by regulatory and operational impact.
                  </div>
                </InsightCard>

                <StatCard title="Citation Coverage" big={insights.coverage.label} pct={insights.coverage.pct} sub={insights.coverage.sub} />
                <StatCard title="Workflow Completeness" big={insights.workflow.label} pct={insights.workflow.pct} sub={insights.workflow.sub} />
                <StatCard title="Persona Relevance Score" big={insights.persona.label} pct={insights.persona.pct} sub={insights.persona.sub} />

                <InsightCard title="Compliance Sensitivity">
                  <div style={{ fontSize: 30, fontWeight: 700, color: insights.compliance.color, letterSpacing: "-.02em" }}>{insights.compliance.label}</div>
                  <div style={{ display: "flex", gap: 6, marginTop: 16 }}>
                    {[0, 1, 2, 3].map((i) => (
                      <div key={i} style={{ flex: 1, height: 9, borderRadius: 2, background: i <= insights.compliance.level ? insights.compliance.color : "var(--line)" }} />
                    ))}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--sub)", marginTop: 14 }}>{insights.compliance.sub}</div>
                </InsightCard>
              </div>
            </div>
            <PageFooter report={report} page={2} />
          </div>
        </section>

        {/* ===== PAGE 3 · RECOMMENDED WORKFLOW ===== */}
        <section className="print-page">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={6}>RECOMMENDED WORKFLOW</SectionTitle>
              <div style={{ fontSize: 13.5, color: "var(--sub)", margin: "14px 0 4px", lineHeight: 1.5 }}>
                A sequenced, evidence-backed plan for the {report.personaTitle} in the {report.marketLabel} market.
              </div>
              {persona.steps.map((s, i) => (
                <div key={s.t} className="avoid-break" style={{ display: "flex", gap: 20, padding: "20px 0", borderBottom: i < persona.steps.length - 1 ? "1px solid var(--line)" : "none" }}>
                  <div style={{ width: 34, height: 34, flex: "none", borderRadius: "50%", border: "1.5px solid #0a0a0b", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: mono, fontSize: 12, fontWeight: 600 }}>
                    {String(i + 1).padStart(2, "0")}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-.01em", color: "var(--ink)" }}>{s.t}</div>
                    <div style={{ display: "flex", gap: 28, marginTop: 12, alignItems: "flex-start" }}>
                      <div style={{ flex: 1 }}>
                        <div style={fieldLabel}>WHY IT MATTERS</div>
                        <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 5, lineHeight: 1.55 }}>{s.d}</div>
                        <div style={{ ...fieldLabel, marginTop: 12 }}>EXPECTED OUTPUT</div>
                        <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 5, lineHeight: 1.55 }}>{s.output}</div>
                      </div>
                      <div style={{ flex: "none", textAlign: "right" }}>
                        <div style={fieldLabel}>EVIDENCE</div>
                        <span style={{ display: "inline-block", marginTop: 7, fontFamily: mono, fontSize: 10.5, fontWeight: 600, color: "#fff", background: "#0a0a0b", padding: "4px 8px", borderRadius: 5, whiteSpace: "nowrap" }}>
                          {WORKFLOW_CITE_TAGS[i % WORKFLOW_CITE_TAGS.length]}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <PageFooter report={report} page={3} />
          </div>
        </section>

        {/* ===== PAGE 4 · RISK REGISTER & EVIDENCE ===== */}
        <section className="print-page">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={0}>RISK REGISTER &amp; EVIDENCE</SectionTitle>
              <div style={{ display: "grid", gridTemplateColumns: RISK_COLS, gap: 14, padding: "14px 0 10px", borderBottom: "1.5px solid #0a0a0b", fontFamily: mono, fontSize: 9, color: "var(--sub)", letterSpacing: ".08em" }}>
                <span>SEVERITY</span>
                <span>RISK</span>
                <span>BUSINESS IMPACT</span>
                <span>EVIDENCE</span>
                <span>RECOMMENDED FIX</span>
                <span>OWNER</span>
              </div>
              {RISKS.map((r) => (
                <div key={r.title} className="avoid-break" style={{ display: "grid", gridTemplateColumns: RISK_COLS, gap: 14, padding: "16px 0", borderBottom: "1px solid var(--line)", alignItems: "start" }}>
                  <SevBadge sev={r.sev} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)", lineHeight: 1.4 }}>{r.title}</span>
                  <span style={{ fontSize: 11.5, color: "var(--ink2)", lineHeight: 1.5 }}>{r.impact}</span>
                  <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: "var(--accent)", lineHeight: 1.4 }}>{r.ref}</span>
                  <span style={{ fontSize: 11.5, color: "var(--ink2)", lineHeight: 1.5 }}>{r.fix}</span>
                  <span style={{ fontSize: 11.5, color: "var(--ink2)", lineHeight: 1.5 }}>{r.owner}</span>
                </div>
              ))}
              <div style={{ display: "flex", gap: 22, marginTop: 22, fontFamily: mono, fontSize: 10, color: "var(--sub)", letterSpacing: ".05em" }}>
                {([["HIGH", SEVERITY_COLORS.HIGH], ["MEDIUM", SEVERITY_COLORS.MED], ["LOW", SEVERITY_COLORS.LOW]] as const).map(([label, color]) => (
                  <div key={label} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: color }} />
                    {label}
                  </div>
                ))}
              </div>
            </div>
            <PageFooter report={report} page={4} />
          </div>
        </section>

        {/* ===== PAGE 5 · SOURCE APPENDIX ===== */}
        <section className="print-page">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={6}>SOURCE APPENDIX</SectionTitle>
              <div style={{ fontSize: 13.5, color: "var(--sub)", margin: "14px 0 4px", lineHeight: 1.5 }}>
                Every claim in this playbook is traceable to a source span in the analyzed corpus.
              </div>
              {CITATIONS.map((c, i) => (
                <div key={c.tag} className="avoid-break" style={{ display: "flex", gap: 14, padding: "14px 0", borderBottom: i < CITATIONS.length - 1 ? "1px solid var(--line)" : "none" }}>
                  <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: "#fff", background: "#0a0a0b", padding: "3px 7px", borderRadius: 5, flex: "none", alignSelf: "flex-start", whiteSpace: "nowrap" }}>{c.tag}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>{c.doc}</div>
                    <div style={{ fontSize: 12.5, color: "var(--ink2)", marginTop: 4, lineHeight: 1.55, fontStyle: "italic" }}>&ldquo;{c.snippet}&rdquo;</div>
                    <div style={{ ...fieldLabel, marginTop: 8 }}>WHY THIS CITATION MATTERS</div>
                    <div style={{ fontSize: 12, color: "var(--sub)", marginTop: 4, lineHeight: 1.5 }}>{c.why}</div>
                  </div>
                </div>
              ))}
            </div>
            <PageFooter report={report} page={5} />
          </div>
        </section>

        {/* ===== PAGE 6 · IMPLEMENTATION CHECKLIST ===== */}
        <section className="print-page">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={6}>IMPLEMENTATION CHECKLIST</SectionTitle>
              <div style={{ fontSize: 13.5, color: "var(--sub)", margin: "14px 0 22px", lineHeight: 1.5 }}>
                Turn this playbook into action. Track the items below through to your next review.
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 22 }}>
                <ChecklistBlock title="IMMEDIATE ACTIONS (0–7 DAYS)" items={persona.actions.slice(0, 3).map((a) => a.title)} />
                <ChecklistBlock
                  title="FOLLOW-UP ACTIONS (2–4 WEEKS)"
                  items={[
                    "Close the highest-severity item in the risk register",
                    "Re-run Evidentia after documentation updates",
                    "Circulate the playbook to the review owner",
                  ]}
                />
              </div>

              <div style={{ marginTop: 24 }}>
                <div style={fieldLabel}>CHECKLIST ITEMS</div>
                <div style={{ marginTop: 12 }}>
                  {persona.steps.map((s) => (
                    <div key={s.t} className="avoid-break" style={{ display: "flex", gap: 12, alignItems: "flex-start", padding: "11px 0", borderBottom: "1px solid var(--line)" }}>
                      <span style={{ width: 16, height: 16, flex: "none", border: "1.5px solid #0a0a0b", borderRadius: 4, marginTop: 1 }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--ink)" }}>{s.t}</div>
                        <div style={{ fontSize: 12, color: "var(--sub)", marginTop: 2, lineHeight: 1.45 }}>{s.output}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 26 }}>
                <div style={{ padding: "16px 18px", border: "1px solid var(--line2)", borderRadius: 9 }}>
                  <div style={fieldLabel}>REVIEW OWNER</div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)", marginTop: 6 }}>{RISKS[0].owner}</div>
                </div>
                <div style={{ padding: "16px 18px", border: "1px solid var(--line2)", borderRadius: 9 }}>
                  <div style={fieldLabel}>NEXT REVIEW DATE</div>
                  <div style={{ fontFamily: mono, fontSize: 14, fontWeight: 600, color: "var(--ink)", marginTop: 8 }}>AUG 04 2026</div>
                </div>
              </div>
            </div>
            <PageFooter report={report} page={6} />
          </div>
        </section>
      </div>
    </div>
  );
}

/* ---------------- helpers ---------------- */

const RISK_COLS = "64px 1.1fr 1.3fr 62px 1.3fr 72px";

const metaLabel: React.CSSProperties = { fontFamily: mono, fontSize: 9, color: "var(--sub)", letterSpacing: ".08em" };
const fieldLabel: React.CSSProperties = { fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".08em" };

function PageHeader({ report, confidential = false, showMeta = true }: { report: DerivedReport; confidential?: boolean; showMeta?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingBottom: 16, borderBottom: "1px solid var(--line)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Logo size={24} showWordmark />
        <span style={{ fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".12em" }}>PERSONA PLAYBOOK</span>
      </div>
      {confidential ? (
        <span style={{ fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".1em" }}>CONFIDENTIAL</span>
      ) : showMeta ? (
        <span style={{ fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".1em" }}>
          {report.personaTitle} · {report.marketLabel}
        </span>
      ) : null}
    </div>
  );
}

function PageFooter({ report, page }: { report: DerivedReport; page: number }) {
  return (
    <div style={{ marginTop: "auto", paddingTop: 20, borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between", fontFamily: mono, fontSize: 9, color: "var(--sub)", letterSpacing: ".08em" }}>
      <span>EVIDENTIA · {report.company} · CONFIDENTIAL</span>
      <span>PAGE {page} / {TOTAL_PAGES}</span>
    </div>
  );
}

function SectionTitle({ children, mb = 16 }: { children: React.ReactNode; mb?: number }) {
  return (
    <div style={{ fontFamily: mono, fontSize: 10.5, color: "#0a0a0b", letterSpacing: ".12em", fontWeight: 600, paddingBottom: 9, borderBottom: "1.5px solid #0a0a0b", marginBottom: mb }}>
      {children}
    </div>
  );
}

function MetaCell({ label, value, mono: isMono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ padding: "15px 16px", borderRight: "1px solid var(--line)" }}>
      <div style={metaLabel}>{label}</div>
      <div style={{ fontFamily: isMono ? mono : undefined, fontSize: isMono ? 11 : 13, fontWeight: isMono ? 500 : 600, marginTop: 6, lineHeight: 1.3 }}>{value}</div>
    </div>
  );
}

function SevBadge({ sev }: { sev: Severity }) {
  return (
    <span style={{ fontFamily: mono, fontSize: 9.5, fontWeight: 600, letterSpacing: ".06em", color: "#fff", background: SEVERITY_COLORS[sev], padding: "4px 8px", borderRadius: 4, flex: "none", lineHeight: 1, whiteSpace: "nowrap", alignSelf: "flex-start" }}>
      {sev}
    </span>
  );
}

function InsightCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="avoid-break" style={{ display: "flex", flexDirection: "column", border: "1px solid var(--line2)", borderRadius: 10, padding: "20px 22px" }}>
      <div style={{ fontFamily: mono, fontSize: 10, color: "var(--sub)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 18 }}>{title}</div>
      {children}
    </div>
  );
}

function StatCard({ title, big, pct, sub }: { title: string; big: string; pct: number; sub: string }) {
  return (
    <div className="avoid-break" style={{ display: "flex", flexDirection: "column", border: "1px solid var(--line2)", borderRadius: 10, padding: "20px 22px" }}>
      <div style={{ fontFamily: mono, fontSize: 10, color: "var(--sub)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 14 }}>{title}</div>
      <div style={{ fontSize: 34, fontWeight: 700, color: "var(--accent)", letterSpacing: "-.02em" }}>{big}</div>
      <div style={{ marginTop: 14 }}>
        <Bar pct={pct} />
      </div>
      <div style={{ fontSize: 12, color: "var(--sub)", marginTop: "auto", paddingTop: 12 }}>{sub}</div>
    </div>
  );
}

function Bar({ pct }: { pct: number }) {
  return (
    <div style={{ height: 7, background: "var(--shell)", borderRadius: 4, overflow: "hidden" }}>
      <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent)", borderRadius: 4 }} />
    </div>
  );
}

function ChecklistBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div style={fieldLabel}>{title}</div>
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((it) => (
          <div key={it} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <span style={{ width: 14, height: 14, flex: "none", border: "1.5px solid #0a0a0b", borderRadius: 4, marginTop: 1 }} />
            <span style={{ fontSize: 12.5, color: "var(--ink2)", lineHeight: 1.4 }}>{it}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
